# 1-Page Architecture Overview

This project is a minimal AWS DevOps demo in **us-east-1** (default), using:

- **AWS CodeCommit** (source)
- **AWS CodeBuild** (test + package)
- **AWS CodePipeline** (orchestration)
- **AWS CodeDeploy** (EC2 deployment)
- **Amazon EC2** (single `t3.micro` app host)
- **Amazon CloudWatch Logs** (app log streaming)

Flow:

1. You push code to the `main` branch in CodeCommit.
2. EventBridge triggers CodePipeline automatically.
3. CodeBuild runs unit tests and creates an artifact with `build_info.json`.
4. CodeDeploy deploys artifact to EC2 using `appspec.yml` hooks:
   - stop app
   - install deps
   - start app
   - validate `/health`
5. App serves:
   - `GET /` -> `Hello DevOps`
   - `GET /health` -> `OK`
   - `GET /version` -> git commit + build timestamp
6. App logs are written to `/var/log/hello-devops/app.log` and streamed to CloudWatch Logs.

---

# Repository File Tree

```text
.
├── .gitignore
├── README.md
├── app.py
├── appspec.yml
├── buildspec.yml
├── infrastructure
│   └── template.yaml
├── requirements.txt
├── scripts
│   ├── install_dependencies.sh
│   ├── start_server.sh
│   ├── stop_server.sh
│   └── validate_service.sh
└── tests
    └── test_app.py
```

---

# File Contents

## `app.py`

```python
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, jsonify

APP_DIR = Path(__file__).resolve().parent
BUILD_INFO_FILE = APP_DIR / "build_info.json"


def _load_build_info() -> dict[str, str]:
    build_info = {
        "git_commit": os.getenv("GIT_COMMIT", "unknown"),
        "build_timestamp": os.getenv("BUILD_TIMESTAMP", "unknown"),
    }

    if BUILD_INFO_FILE.exists():
        try:
            file_data = json.loads(BUILD_INFO_FILE.read_text(encoding="utf-8"))
            build_info["git_commit"] = file_data.get("git_commit", build_info["git_commit"])
            build_info["build_timestamp"] = file_data.get("build_timestamp", build_info["build_timestamp"])
        except (json.JSONDecodeError, OSError):
            pass

    return build_info


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def hello() -> str:
        return "Hello DevOps"

    @app.get("/health")
    def health() -> str:
        return "OK"

    @app.get("/version")
    def version():
        return jsonify(_load_build_info())

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
```

## `requirements.txt`

```txt
Flask==3.0.3
```

## `tests/test_app.py`

```python
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class HelloDevOpsAppTests(unittest.TestCase):
    def setUp(self):
        self.client = app.create_app().test_client()

    def test_root_endpoint(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), "Hello DevOps")

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), "OK")

    def test_version_endpoint_uses_env_defaults(self):
        with patch.dict(os.environ, {"GIT_COMMIT": "abc123", "BUILD_TIMESTAMP": "2026-01-01T00:00:00Z"}, clear=False):
            with patch.object(app, "BUILD_INFO_FILE", Path("/non/existent/build_info.json")):
                response = self.client.get("/version")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode("utf-8"))
        self.assertEqual(payload["git_commit"], "abc123")
        self.assertEqual(payload["build_timestamp"], "2026-01-01T00:00:00Z")

    def test_version_endpoint_prefers_build_info_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            build_info_path = Path(tmpdir) / "build_info.json"
            build_info_path.write_text(
                json.dumps({"git_commit": "file-commit", "build_timestamp": "2026-02-02T00:00:00+00:00"}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"GIT_COMMIT": "env-commit", "BUILD_TIMESTAMP": "env-time"}, clear=False):
                with patch.object(app, "BUILD_INFO_FILE", build_info_path):
                    response = self.client.get("/version")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode("utf-8"))
        self.assertEqual(payload["git_commit"], "file-commit")
        self.assertEqual(payload["build_timestamp"], "2026-02-02T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
```

## `buildspec.yml`

```yaml
version: 0.2

phases:
  install:
    runtime-versions:
      python: 3.11
    commands:
      - pip install --upgrade pip
      - pip install -r requirements.txt
  pre_build:
    commands:
      - python -m unittest discover -s tests -v
  build:
    commands:
      - echo "Build stage completed"
  post_build:
    commands:
      - |
        python - <<'PY'
        import json
        import os
        from datetime import datetime, timezone

        build_info = {
            "git_commit": os.getenv("CODEBUILD_RESOLVED_SOURCE_VERSION", "unknown"),
            "build_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open("build_info.json", "w", encoding="utf-8") as f:
            json.dump(build_info, f)
        PY

artifacts:
  files:
    - app.py
    - requirements.txt
    - build_info.json
    - appspec.yml
    - scripts/**/*
```

## `appspec.yml`

```yaml
version: 0.0
os: linux
files:
  - source: /
    destination: /opt/hello-devops
permissions:
  - object: /opt/hello-devops
    pattern: "**"
    owner: root
    group: root
    mode: 755
hooks:
  ApplicationStop:
    - location: scripts/stop_server.sh
      timeout: 60
      runas: root
  AfterInstall:
    - location: scripts/install_dependencies.sh
      timeout: 300
      runas: root
  ApplicationStart:
    - location: scripts/start_server.sh
      timeout: 60
      runas: root
  ValidateService:
    - location: scripts/validate_service.sh
      timeout: 60
      runas: root
```

## `scripts/install_dependencies.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/hello-devops"
LOG_DIR="/var/log/hello-devops"

mkdir -p "${LOG_DIR}"
python3 -m pip install --upgrade pip
python3 -m pip install -r "${APP_DIR}/requirements.txt"
```

## `scripts/start_server.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/hello-devops"
LOG_DIR="/var/log/hello-devops"
PID_FILE="/var/run/hello-devops.pid"

mkdir -p "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
  CURRENT_PID="$(cat "${PID_FILE}")"
  if python3 -c "import os; os.kill(int('${CURRENT_PID}'), 0)" 2>/dev/null; then
    echo "App is already running"
    exit 0
  fi
fi

cd "${APP_DIR}"
PORT=80 nohup python3 app.py >> "${LOG_DIR}/app.log" 2>&1 &
echo $! > "${PID_FILE}"
```

## `scripts/stop_server.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/var/run/hello-devops.pid"

if [[ -f "${PID_FILE}" ]]; then
  CURRENT_PID="$(cat "${PID_FILE}")"
  python3 - <<PY
import os
import signal

pid = int("${CURRENT_PID}")
try:
    os.kill(pid, signal.SIGTERM)
except ProcessLookupError:
    pass
PY
  rm -f "${PID_FILE}"
fi
```

## `scripts/validate_service.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health)"
if [[ "${HTTP_STATUS}" != "200" ]]; then
  echo "Health check failed. Status: ${HTTP_STATUS}"
  exit 1
fi

echo "Health check passed"
```

## `infrastructure/template.yaml` (full IaC template)

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: Minimal AWS DevOps demo (CodeCommit -> CodeBuild -> CodeDeploy -> EC2)

Parameters:
  ProjectName:
    Type: String
    Default: hello-devops
  BranchName:
    Type: String
    Default: main
  InstanceType:
    Type: String
    Default: t3.micro
  KeyPairName:
    Type: AWS::EC2::KeyPair::KeyName
    Description: Optional key pair for emergency SSH access
  VpcId:
    Type: AWS::EC2::VPC::Id
  SubnetId:
    Type: AWS::EC2::Subnet::Id

Resources:
  ArtifactBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256

  CodeCommitRepository:
    Type: AWS::CodeCommit::Repository
    Properties:
      RepositoryName: !Sub '${ProjectName}-repo'
      RepositoryDescription: Source repository for hello devops app

  AppLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub '/aws/${ProjectName}/app'
      RetentionInDays: 14

  AppSecurityGroup:
    Type: AWS::EC2::SecurityGroup
    Properties:
      GroupDescription: Allow HTTP traffic
      VpcId: !Ref VpcId
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: 80
          ToPort: 80
          CidrIp: 0.0.0.0/0
      SecurityGroupEgress:
        - IpProtocol: -1
          CidrIp: 0.0.0.0/0

  EC2InstanceRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: ec2.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
      Policies:
        - PolicyName: EC2CodeDeployAndLogs
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - s3:GetObject
                  - s3:GetObjectVersion
                  - s3:ListBucket
                Resource:
                  - !GetAtt ArtifactBucket.Arn
                  - !Sub '${ArtifactBucket.Arn}/*'
              - Effect: Allow
                Action:
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                  - logs:DescribeLogStreams
                Resource: !Sub '${AppLogGroup.Arn}:*'
              - Effect: Allow
                Action:
                  - codedeploy:PutLifecycleEventHookExecutionStatus
                  - codedeploy:GetDeployment
                  - codedeploy:GetDeploymentInstance
                Resource: '*'

  EC2InstanceProfile:
    Type: AWS::IAM::InstanceProfile
    Properties:
      Roles:
        - !Ref EC2InstanceRole

  DemoInstance:
    Type: AWS::EC2::Instance
    Properties:
      ImageId: ami-0f88e80871fd81e91
      InstanceType: !Ref InstanceType
      IamInstanceProfile: !Ref EC2InstanceProfile
      KeyName: !Ref KeyPairName
      SecurityGroupIds:
        - !Ref AppSecurityGroup
      SubnetId: !Ref SubnetId
      Tags:
        - Key: Name
          Value: !Sub '${ProjectName}-ec2'
        - Key: CodeDeployGroup
          Value: !Sub '${ProjectName}-dg'
      UserData:
        Fn::Base64: !Sub |
          #!/bin/bash
          set -euxo pipefail
          dnf update -y
          dnf install -y ruby python3 python3-pip curl wget jq awslogs

          cd /tmp
          wget https://aws-codedeploy-${AWS::Region}.s3.${AWS::Region}.amazonaws.com/latest/install
          chmod +x ./install
          ./install auto
          systemctl enable codedeploy-agent
          systemctl start codedeploy-agent

          cat > /etc/awslogs/awscli.conf <<EOF
          [plugins]
          cwlogs = cwlogs
          [default]
          region = ${AWS::Region}
          EOF

          cat > /etc/awslogs/awslogs.conf <<EOF
          [general]
          state_file = /var/lib/awslogs/agent-state

          [/var/log/hello-devops/app.log]
          file = /var/log/hello-devops/app.log
          log_group_name = /aws/${ProjectName}/app
          log_stream_name = {instance_id}
          datetime_format = %Y-%m-%d %H:%M:%S
          EOF

          mkdir -p /var/log/hello-devops
          touch /var/log/hello-devops/app.log
          systemctl enable awslogsd
          systemctl restart awslogsd

  CodeDeployApplication:
    Type: AWS::CodeDeploy::Application
    Properties:
      ComputePlatform: Server
      ApplicationName: !Sub '${ProjectName}-app'

  CodeDeployServiceRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: codedeploy.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSCodeDeployRole

  CodeDeployDeploymentGroup:
    Type: AWS::CodeDeploy::DeploymentGroup
    Properties:
      ApplicationName: !Ref CodeDeployApplication
      DeploymentConfigName: CodeDeployDefault.OneAtATime
      DeploymentGroupName: !Sub '${ProjectName}-dg'
      ServiceRoleArn: !GetAtt CodeDeployServiceRole.Arn
      Ec2TagFilters:
        - Key: CodeDeployGroup
          Type: KEY_AND_VALUE
          Value: !Sub '${ProjectName}-dg'
      AutoRollbackConfiguration:
        Enabled: true
        Events:
          - DEPLOYMENT_FAILURE
          - DEPLOYMENT_STOP_ON_ALARM
          - DEPLOYMENT_STOP_ON_REQUEST

  CodeBuildRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: codebuild.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: CodeBuildPolicy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - logs:CreateLogGroup
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                Resource: '*'
              - Effect: Allow
                Action:
                  - s3:GetObject
                  - s3:GetObjectVersion
                  - s3:PutObject
                Resource:
                  - !GetAtt ArtifactBucket.Arn
                  - !Sub '${ArtifactBucket.Arn}/*'
              - Effect: Allow
                Action:
                  - codecommit:GitPull
                Resource: !GetAtt CodeCommitRepository.Arn

  CodeBuildProject:
    Type: AWS::CodeBuild::Project
    Properties:
      Name: !Sub '${ProjectName}-build'
      ServiceRole: !GetAtt CodeBuildRole.Arn
      Artifacts:
        Type: CODEPIPELINE
      Environment:
        ComputeType: BUILD_GENERAL1_SMALL
        Image: aws/codebuild/standard:7.0
        Type: LINUX_CONTAINER
      Source:
        Type: CODEPIPELINE
        BuildSpec: buildspec.yml

  CodePipelineRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: codepipeline.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: CodePipelinePolicy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - s3:GetObject
                  - s3:GetObjectVersion
                  - s3:PutObject
                Resource:
                  - !GetAtt ArtifactBucket.Arn
                  - !Sub '${ArtifactBucket.Arn}/*'
              - Effect: Allow
                Action:
                  - codecommit:GetBranch
                  - codecommit:GetCommit
                  - codecommit:UploadArchive
                  - codecommit:GetUploadArchiveStatus
                  - codecommit:CancelUploadArchive
                Resource: !GetAtt CodeCommitRepository.Arn
              - Effect: Allow
                Action:
                  - codebuild:BatchGetBuilds
                  - codebuild:StartBuild
                Resource: !GetAtt CodeBuildProject.Arn
              - Effect: Allow
                Action:
                  - codedeploy:CreateDeployment
                  - codedeploy:GetApplicationRevision
                  - codedeploy:GetDeployment
                  - codedeploy:GetDeploymentConfig
                  - codedeploy:RegisterApplicationRevision
                Resource: '*'
              - Effect: Allow
                Action: iam:PassRole
                Resource:
                  - !GetAtt CodeBuildRole.Arn
                  - !GetAtt CodeDeployServiceRole.Arn

  Pipeline:
    Type: AWS::CodePipeline::Pipeline
    Properties:
      Name: !Sub '${ProjectName}-pipeline'
      RoleArn: !GetAtt CodePipelineRole.Arn
      ArtifactStore:
        Type: S3
        Location: !Ref ArtifactBucket
      Stages:
        - Name: Source
          Actions:
            - Name: Source
              ActionTypeId:
                Category: Source
                Owner: AWS
                Provider: CodeCommit
                Version: '1'
              OutputArtifacts:
                - Name: SourceArtifact
              Configuration:
                RepositoryName: !GetAtt CodeCommitRepository.Name
                BranchName: !Ref BranchName
                PollForSourceChanges: false
              RunOrder: 1
        - Name: Build
          Actions:
            - Name: Build
              ActionTypeId:
                Category: Build
                Owner: AWS
                Provider: CodeBuild
                Version: '1'
              InputArtifacts:
                - Name: SourceArtifact
              OutputArtifacts:
                - Name: BuildArtifact
              Configuration:
                ProjectName: !Ref CodeBuildProject
              RunOrder: 1
        - Name: Deploy
          Actions:
            - Name: DeployToEC2
              ActionTypeId:
                Category: Deploy
                Owner: AWS
                Provider: CodeDeploy
                Version: '1'
              InputArtifacts:
                - Name: BuildArtifact
              Configuration:
                ApplicationName: !Ref CodeDeployApplication
                DeploymentGroupName: !Ref CodeDeployDeploymentGroup
              RunOrder: 1

  PipelineTriggerRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: events.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: StartPipelineExecution
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action: codepipeline:StartPipelineExecution
                Resource: !Sub 'arn:aws:codepipeline:${AWS::Region}:${AWS::AccountId}:${Pipeline}'

  CodeCommitChangeRule:
    Type: AWS::Events::Rule
    Properties:
      Description: Trigger pipeline on CodeCommit updates
      EventPattern:
        source:
          - aws.codecommit
        detail-type:
          - CodeCommit Repository State Change
        resources:
          - !GetAtt CodeCommitRepository.Arn
        detail:
          event:
            - referenceCreated
            - referenceUpdated
          referenceType:
            - branch
          referenceName:
            - !Ref BranchName
      Targets:
        - Arn: !Sub 'arn:aws:codepipeline:${AWS::Region}:${AWS::AccountId}:${Pipeline}'
          Id: CodePipelineTarget
          RoleArn: !GetAtt PipelineTriggerRole.Arn

Outputs:
  RepositoryCloneUrlHttp:
    Value: !GetAtt CodeCommitRepository.CloneUrlHttp
  PipelineName:
    Value: !Ref Pipeline
  InstancePublicIp:
    Value: !GetAtt DemoInstance.PublicIp
```

## `.gitignore`

```txt
__pycache__/
*.pyc
.pytest_cache/
.venv/
```

---

# Step-by-Step Deployment (CLI + Console)

> Default region is **us-east-1**. To use another region, set `AWS_REGION` and deploy there.

## 1) Prerequisites

- AWS CLI v2 configured (`aws configure`)
- Permissions to create IAM, EC2, Code* services, CloudFormation, S3, Logs
- Existing VPC + subnet in target region
- Existing EC2 key pair name

## 2) Deploy infrastructure

```bash
export AWS_REGION=us-east-1
export STACK_NAME=hello-devops-stack
export VPC_ID=vpc-xxxxxxxx
export SUBNET_ID=subnet-xxxxxxxx
export KEY_NAME=your-keypair

aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name "$STACK_NAME" \
  --template-file infrastructure/template.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName=hello-devops \
    BranchName=main \
    InstanceType=t3.micro \
    VpcId="$VPC_ID" \
    SubnetId="$SUBNET_ID" \
    KeyPairName="$KEY_NAME"
```

## 3) Get outputs

```bash
aws cloudformation describe-stacks \
  --region "$AWS_REGION" \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs"
```

Copy `RepositoryCloneUrlHttp`, `PipelineName`, and `InstancePublicIp`.

## 4) Push this repo to CodeCommit (main branch)

```bash
REPO_URL=<RepositoryCloneUrlHttp-from-outputs>
git remote add aws "$REPO_URL"
git push aws main
```

If your branch is not named `main`:

```bash
git push aws HEAD:main
```

## 5) Confirm pipeline run

- Open **CodePipeline** console -> `hello-devops-pipeline`
- Verify **Source -> Build -> Deploy** stages succeed

---

# Validation Steps

## API checks

```bash
APP_IP=<InstancePublicIp-from-outputs>
curl "http://$APP_IP/"
curl "http://$APP_IP/health"
curl "http://$APP_IP/version"
```

Expected:

- `/` -> `Hello DevOps`
- `/health` -> `OK`
- `/version` -> JSON with commit hash + build timestamp

## Logs

- **Build logs**: CodeBuild -> Build history -> specific build -> logs
- **Deploy logs**: CodeDeploy -> deployment -> lifecycle event logs
- **App logs**:
  - CloudWatch Logs group: `/aws/hello-devops/app`
  - EC2 local file: `/var/log/hello-devops/app.log`

---

# IAM Least-Privilege Notes

- **CodeBuild role**: logs + artifact bucket read/write + CodeCommit pull.
- **CodeDeploy role**: AWS managed `AWSCodeDeployRole`.
- **CodePipeline role**: source/build/deploy orchestration actions + scoped `iam:PassRole`.
- **EC2 role**: SSM, S3 artifact read, and CloudWatch Logs stream write.

These can be tightened further by restricting wildcard resources after first successful run.

---

# Rollback Strategy

`CodeDeployDeploymentGroup` enables auto-rollback:

- `DEPLOYMENT_FAILURE`
- `DEPLOYMENT_STOP_ON_ALARM`
- `DEPLOYMENT_STOP_ON_REQUEST`

If validation (`/health`) fails in `ValidateService`, deployment is marked failed and rollback is triggered.

---

# Troubleshooting

- **Pipeline not triggered on push**
  - Verify EventBridge rule is enabled.
  - Ensure push is to configured branch (`main`).
- **Build fails**
  - Check CodeBuild logs for dependency/test errors.
- **Deploy fails**
  - Check CodeDeploy lifecycle event details.
  - Verify EC2 has running CodeDeploy agent:
    - `sudo systemctl status codedeploy-agent`
- **App not reachable**
  - Confirm security group allows inbound TCP/80.
  - Confirm app process:
    - `ps -ef | grep app.py`
    - `cat /var/log/hello-devops/app.log`

---

# Cost Minimization

- Use one **t3.micro** instance.
- Keep one pipeline + one build project.
- Set log retention (14 days).
- Delete stack after demo.

---

# Teardown / Cleanup

1. Stop further pushes to CodeCommit.
2. Delete CloudFormation stack:

```bash
aws cloudformation delete-stack \
  --region "$AWS_REGION" \
  --stack-name "$STACK_NAME"
```

3. Confirm all resources are deleted in:
   - CloudFormation
   - CodePipeline
   - CodeBuild
   - CodeDeploy
   - EC2
   - CloudWatch Logs
   - S3 (artifact bucket)

---

# Optional Alternate Source (GitHub)

Primary path in this project is **CodeCommit** for simplicity.  
If needed, you can switch CodePipeline source to GitHub (via CodeConnections) with minimal stage changes.
