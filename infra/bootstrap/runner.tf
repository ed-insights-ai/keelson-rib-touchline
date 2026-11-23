# ---------------------------------------------------------------------------
# The PrestoSports runner: one small EC2 instance, registered to the rib as a
# self-hosted GitHub Actions runner labelled `presto`.
#
# PrestoSports refuses GitHub-hosted runners (HTTP 405) but serves AWS
# addresses (checked from CloudShell, 2026-11-23). The Collect workflow starts
# this instance just before it queues the presto job, and the instance stops
# itself once no job has run for a while (runner-user-data.sh), so it runs
# about an hour a day in season.
#
# It lives in bootstrap because nothing in GitHub Actions may create compute:
# the infra role has no EC2 permissions, and the publish role may only start
# this one instance (the boundary in iam.tf, the grant in infra/main/iam.tf).
#
# The instance holds no secrets. The presto job gets only its work home as an
# artifact, and the instance role allows Systems Manager access and nothing
# else. No inbound port is open; Daniel reaches it through Systems Manager.
#
# One fixed address (var.runner_fixed_address) keeps the collector a single,
# recognisable source to the schools' sites rather than a new address a day.
#
# Out of season: set presto_runner = false and apply; everything here is
# destroyed and costs nothing. GitHub forgets a runner it has not seen for 14
# days, so a new season means applying and registering again either way.
# ---------------------------------------------------------------------------

locals {
  runner_count = var.presto_runner ? 1 : 0
  # The tag the publish role's start permission is conditioned on.
  runner_role_tag = "presto-runner"
}

# Ubuntu 24.04, the image family GitHub's own ubuntu-latest runners use, so
# the job behaves the same on both.
data "aws_ssm_parameter" "runner_ami" {
  count = local.runner_count
  name  = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

data "aws_availability_zones" "available" {
  count = local.runner_count
  state = "available"
}

# A network of its own, so nothing depends on the account's default VPC.
resource "aws_vpc" "runner" {
  count                = local.runner_count
  cidr_block           = "10.83.0.0/24"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "touchline-presto-runner" }
}

resource "aws_internet_gateway" "runner" {
  count  = local.runner_count
  vpc_id = aws_vpc.runner[0].id

  tags = { Name = "touchline-presto-runner" }
}

resource "aws_subnet" "runner" {
  count                   = local.runner_count
  vpc_id                  = aws_vpc.runner[0].id
  cidr_block              = "10.83.0.0/26"
  availability_zone       = data.aws_availability_zones.available[0].names[0]
  map_public_ip_on_launch = true

  tags = { Name = "touchline-presto-runner" }
}

resource "aws_route_table" "runner" {
  count  = local.runner_count
  vpc_id = aws_vpc.runner[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.runner[0].id
  }

  tags = { Name = "touchline-presto-runner" }
}

resource "aws_route_table_association" "runner" {
  count          = local.runner_count
  subnet_id      = aws_subnet.runner[0].id
  route_table_id = aws_route_table.runner[0].id
}

# Outbound web only. Nothing comes in.
resource "aws_security_group" "runner" {
  count       = local.runner_count
  name        = "touchline-presto-runner"
  description = "PrestoSports runner: outbound web only, no inbound"
  vpc_id      = aws_vpc.runner[0].id

  egress {
    description = "HTTPS to GitHub, school sites and Systems Manager"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "HTTP, for package mirrors and sites that redirect from it"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "touchline-presto-runner" }
}

# The instance's own role: Systems Manager, so Daniel can register the runner
# and read its logs without SSH. No data, signing or deploy permissions.
data "aws_iam_policy_document" "runner_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "runner" {
  count              = local.runner_count
  name               = "touchline-presto-runner"
  description        = "Instance role of the PrestoSports runner: Systems Manager only"
  assume_role_policy = data.aws_iam_policy_document.runner_trust.json
}

resource "aws_iam_role_policy_attachment" "runner_ssm" {
  count      = local.runner_count
  role       = aws_iam_role.runner[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "runner" {
  count = local.runner_count
  name  = "touchline-presto-runner"
  role  = aws_iam_role.runner[0].name
}

resource "aws_instance" "runner" {
  count                  = local.runner_count
  ami                    = data.aws_ssm_parameter.runner_ami[0].value
  instance_type          = var.runner_instance_type
  subnet_id              = aws_subnet.runner[0].id
  vpc_security_group_ids = [aws_security_group.runner[0].id]
  iam_instance_profile   = aws_iam_instance_profile.runner[0].name

  # The idle stop powers the machine off; that must stop it, never end it,
  # or the runner's registration would be lost every day.
  instance_initiated_shutdown_behavior = "stop"

  user_data = templatefile("${path.module}/runner-user-data.sh", {
    repo         = local.repo
    idle_minutes = var.runner_idle_minutes
  })

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # Not encrypted on purpose: the disk holds a checkout and public pages, and
  # starting an instance with an encrypted disk needs KMS grants the publish
  # role's boundary does not give.
  root_block_device {
    volume_type = "gp3"
    volume_size = 12
    encrypted   = false
  }

  tags = {
    Name           = "touchline-presto-runner"
    touchline-role = local.runner_role_tag
  }

  lifecycle {
    # A newer image or an edited setup script must not replace the machine
    # mid-season: that would drop the runner's registration. To rebuild on
    # purpose, taint it (see the guide).
    ignore_changes = [ami, user_data]
  }

  depends_on = [aws_route_table_association.runner]
}

resource "aws_eip" "runner" {
  count    = var.presto_runner && var.runner_fixed_address ? 1 : 0
  domain   = "vpc"
  instance = aws_instance.runner[0].id

  tags = { Name = "touchline-presto-runner" }

  depends_on = [aws_internet_gateway.runner]
}
