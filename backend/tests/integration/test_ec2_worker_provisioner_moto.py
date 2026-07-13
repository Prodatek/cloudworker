import uuid

import boto3
import pytest
from moto import mock_aws

from app.domain.worker_provisioner import ProvisioningError
from app.infrastructure.aws.ec2_worker_provisioner import EC2WorkerProvisioner


def _create_launch_template(ec2_client, ami_id: str) -> str:
    response = ec2_client.create_launch_template(
        LaunchTemplateName="cloudworker-worker-test",
        LaunchTemplateData={"ImageId": ami_id, "InstanceType": "t3.micro"},
    )
    return response["LaunchTemplate"]["LaunchTemplateId"]


# mock_aws is used as a context manager (not a decorator) below: moto's decorator form
# isn't async-aware and pytest-asyncio silently skips `async def` tests wrapped by it.


async def test_launch_creates_instance_from_launch_template_with_job_tag() -> None:
    with mock_aws():
        region = "us-east-1"
        ec2_client = boto3.client("ec2", region_name=region)
        images = ec2_client.describe_images()["Images"]
        ami_id = images[0]["ImageId"]

        vpc_id = ec2_client.create_vpc(CidrBlock="10.42.0.0/16")["Vpc"]["VpcId"]
        subnet_id = ec2_client.create_subnet(VpcId=vpc_id, CidrBlock="10.42.0.0/24")["Subnet"][
            "SubnetId"
        ]
        launch_template_id = _create_launch_template(ec2_client, ami_id)

        provisioner = EC2WorkerProvisioner(
            region=region,
            launch_template_id=launch_template_id,
            subnet_ids=[subnet_id],
        )

        job_id = uuid.uuid4()
        instance_id = await provisioner.launch(job_id)

        instances = ec2_client.describe_instances(InstanceIds=[instance_id])["Reservations"][0][
            "Instances"
        ]
        assert len(instances) == 1
        instance = instances[0]
        assert instance["SubnetId"] == subnet_id
        assert instance["State"]["Name"] in ("pending", "running")
        tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
        assert tags["cloudworker:job-id"] == str(job_id)


async def test_terminate_stops_the_instance() -> None:
    with mock_aws():
        region = "us-east-1"
        ec2_client = boto3.client("ec2", region_name=region)
        ami_id = ec2_client.describe_images()["Images"][0]["ImageId"]
        vpc_id = ec2_client.create_vpc(CidrBlock="10.42.0.0/16")["Vpc"]["VpcId"]
        subnet_id = ec2_client.create_subnet(VpcId=vpc_id, CidrBlock="10.42.0.0/24")["Subnet"][
            "SubnetId"
        ]
        launch_template_id = _create_launch_template(ec2_client, ami_id)
        provisioner = EC2WorkerProvisioner(
            region=region, launch_template_id=launch_template_id, subnet_ids=[subnet_id]
        )
        instance_id = await provisioner.launch(uuid.uuid4())

        await provisioner.terminate(instance_id)

        instance = ec2_client.describe_instances(InstanceIds=[instance_id])["Reservations"][0][
            "Instances"
        ][0]
        assert instance["State"]["Name"] in ("shutting-down", "terminated")


async def test_launch_raises_provisioning_error_for_unknown_launch_template() -> None:
    with mock_aws():
        region = "us-east-1"
        ec2_client = boto3.client("ec2", region_name=region)
        vpc_id = ec2_client.create_vpc(CidrBlock="10.42.0.0/16")["Vpc"]["VpcId"]
        subnet_id = ec2_client.create_subnet(VpcId=vpc_id, CidrBlock="10.42.0.0/24")["Subnet"][
            "SubnetId"
        ]
        provisioner = EC2WorkerProvisioner(
            region=region, launch_template_id="lt-doesnotexist", subnet_ids=[subnet_id]
        )

        with pytest.raises(ProvisioningError):
            await provisioner.launch(uuid.uuid4())
