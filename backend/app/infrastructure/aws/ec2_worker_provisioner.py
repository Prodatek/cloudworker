import asyncio
import random
import time
import uuid

import boto3

from app.domain.worker_provisioner import ProvisioningError

_JOB_ID_TAG_KEY = "cloudworker:job-id"


class EC2WorkerProvisioner:
    """boto3-based WorkerProvisioner: launches/terminates EC2 instances from Phase 3's
    launch template and polls SSM for registration.
    """

    def __init__(
        self,
        region: str,
        launch_template_id: str,
        subnet_ids: list[str],
        ssm_poll_interval_seconds: float = 5.0,
    ) -> None:
        if not subnet_ids:
            raise ValueError("At least one worker subnet id must be configured")
        self._launch_template_id = launch_template_id
        self._subnet_ids = subnet_ids
        self._ssm_poll_interval_seconds = ssm_poll_interval_seconds
        self._ec2 = boto3.client("ec2", region_name=region)
        self._ssm = boto3.client("ssm", region_name=region)

    async def launch(self, job_id: uuid.UUID) -> str:
        subnet_id = random.choice(self._subnet_ids)
        try:
            response = await asyncio.to_thread(
                self._ec2.run_instances,
                LaunchTemplate={"LaunchTemplateId": self._launch_template_id},
                SubnetId=subnet_id,
                MinCount=1,
                MaxCount=1,
                TagSpecifications=[
                    {
                        "ResourceType": "instance",
                        "Tags": [{"Key": _JOB_ID_TAG_KEY, "Value": str(job_id)}],
                    }
                ],
            )
        except Exception as exc:
            raise ProvisioningError(f"Failed to launch worker instance: {exc}") from exc

        return str(response["Instances"][0]["InstanceId"])

    async def wait_until_ssm_ready(self, instance_id: str, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while True:
            response = await asyncio.to_thread(
                self._ssm.describe_instance_information,
                Filters=[{"Key": "InstanceIds", "Values": [instance_id]}],
            )
            if response.get("InstanceInformationList"):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self._ssm_poll_interval_seconds)

    async def terminate(self, instance_id: str) -> None:
        await asyncio.to_thread(self._ec2.terminate_instances, InstanceIds=[instance_id])
