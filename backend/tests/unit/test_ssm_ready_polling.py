from unittest.mock import MagicMock

from app.infrastructure.aws.ec2_worker_provisioner import EC2WorkerProvisioner

# moto can't simulate an EC2 instance's SSM Agent actually checking in (that's real agent
# behavior, not something moto tracks), so wait_until_ssm_ready()'s retry/timeout logic is
# tested here against a hand-mocked SSM client response sequence instead.


def _make_provisioner() -> EC2WorkerProvisioner:
    provisioner = EC2WorkerProvisioner(
        region="us-east-1",
        launch_template_id="lt-fake",
        subnet_ids=["subnet-fake1"],
        ssm_poll_interval_seconds=0.01,
    )
    return provisioner


async def test_wait_until_ssm_ready_returns_true_once_instance_registers() -> None:
    provisioner = _make_provisioner()
    responses = [
        {"InstanceInformationList": []},
        {"InstanceInformationList": []},
        {"InstanceInformationList": [{"InstanceId": "i-fake00000001"}]},
    ]
    provisioner._ssm = MagicMock()
    provisioner._ssm.describe_instance_information.side_effect = responses

    ready = await provisioner.wait_until_ssm_ready("i-fake00000001", timeout_seconds=5)

    assert ready is True
    assert provisioner._ssm.describe_instance_information.call_count == 3


async def test_wait_until_ssm_ready_returns_false_on_timeout() -> None:
    provisioner = _make_provisioner()
    provisioner._ssm = MagicMock()
    provisioner._ssm.describe_instance_information.return_value = {"InstanceInformationList": []}

    ready = await provisioner.wait_until_ssm_ready("i-fake00000001", timeout_seconds=0.05)

    assert ready is False
    assert provisioner._ssm.describe_instance_information.call_count >= 1
