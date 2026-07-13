packer {
  required_plugins {
    amazon = {
      version = ">= 1.2.0"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  description = "Build-time instance type. Unrelated to the instance_type CloudWorker workers actually launch as (that's Terraform's compute module)."
  type    = string
  default = "t3.medium"
}

variable "ami_name_prefix" {
  type    = string
  default = "cloudworker-worker"
}

# Same base AL2023 image Phase 3's launch template already references — this build
# layers Playwright on top of it rather than starting from something different.
data "amazon-ami" "al2023" {
  filters = {
    name                = "al2023-ami-*-x86_64"
    root-device-type    = "ebs"
    virtualization-type = "hvm"
  }
  most_recent = true
  owners      = ["amazon"]
  region      = var.aws_region
}

source "amazon-ebs" "worker" {
  ami_name      = "${var.ami_name_prefix}-{{timestamp}}"
  instance_type = var.instance_type
  region        = var.aws_region
  source_ami    = data.amazon-ami.al2023.id
  ssh_username  = "ec2-user"

  tags = {
    Project   = "cloudworker"
    ManagedBy = "packer"
  }
}

build {
  sources = ["source.amazon-ebs.worker"]

  provisioner "shell" {
    script = "scripts/install_playwright.sh"
  }

  provisioner "file" {
    source      = "scripts/run_playwright.py"
    destination = "/tmp/run_playwright.py"
  }

  provisioner "shell" {
    inline = [
      "sudo mkdir -p /opt/cloudworker",
      "sudo mv /tmp/run_playwright.py /opt/cloudworker/run_playwright.py",
      "sudo chmod 755 /opt/cloudworker/run_playwright.py",
    ]
  }
}
