"""
Curated seed URLs and crawl boundary rules for AWS documentation sources.
Each entry maps a human-readable key to metadata the scraper uses.
"""

# Domains allowed during crawling — scraper will not follow links outside these
ALLOWED_DOMAINS = {
    "docs.aws.amazon.com",
    "aws.amazon.com",
}

# URL path prefixes that define the crawl boundary per source.
# The scraper will only follow links whose path starts with one of these.
CRAWL_BOUNDARIES = {
    "docs.aws.amazon.com": [
        "/lambda/",
        "/AmazonS3/",
        "/AmazonRDS/",
        "/AWSEC2/",
        "/AmazonECS/",
        "/eks/",
        "/vpc/",
        "/IAM/",
        "/AWSCloudFormation/",
        "/sagemaker/",
        "/glue/",
        "/kinesis/",
        "/amazondynamodb/",
        "/redshift/",
        "/sns/",
        "/AWSSimpleQueueService/",
        "/apigateway/",
        "/AmazonCloudWatch/",
        "/step-functions/",
        "/eventbridge/",
        "/bedrock/",
        "/bedrock-agentcore/",
        "/transfer/",
        "/datasync/",
        "/storagegateway/",
        "/efs/",
        "/fsx/",
        "/AmazonElastiCache/",
        "/kms/",
        "/cognito/",
        "/guardduty/",
        "/securityhub/",
        "/waf/",
        "/athena/",
        "/emr/",
        "/quicksight/",
        "/codecommit/",
        "/codebuild/",
        "/codedeploy/",
        "/codepipeline/",
        "/cloudtrail/",
        "/config/",
        "/organizations/",
        "/systems-manager/",
        "/route53/",
        "/cloudfront/",
        "/elasticloadbalancing/",
        "/msk/",
        "/opensearch-service/",
        "/comprehend/",
        "/rekognition/",
        "/textract/",
        "/translate/",
        "/lex/",
        "/polly/",
        "/transcribe/",
        "/forecast/",
        "/personalize/",
        "/cdk/",
        "/appflow/",
    ],
    "aws.amazon.com": [
        "/solutions/",
        "/prescriptive-guidance/",
        "/architecture/",
    ],
}

# Seed URLs organised by source key.
# These are the starting points for each crawl.
SEED_URLS = {
    # ── Compute ────────────────────────────────────────────────────────────
    "lambda": {
        "name": "AWS Lambda Developer Guide",
        "url": "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "ec2": {
        "name": "Amazon EC2 User Guide",
        "url": "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/concepts.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "ecs": {
        "name": "Amazon ECS Developer Guide",
        "url": "https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "eks": {
        "name": "Amazon EKS User Guide",
        "url": "https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    # ── Storage ────────────────────────────────────────────────────────────
    "s3": {
        "name": "Amazon S3 User Guide",
        "url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "efs": {
        "name": "Amazon EFS User Guide",
        "url": "https://docs.aws.amazon.com/efs/latest/ug/whatisefs.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    # ── Database ───────────────────────────────────────────────────────────
    "rds": {
        "name": "Amazon RDS User Guide",
        "url": "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "dynamodb": {
        "name": "Amazon DynamoDB Developer Guide",
        "url": "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "redshift": {
        "name": "Amazon Redshift Database Developer Guide",
        "url": "https://docs.aws.amazon.com/redshift/latest/dg/welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "elasticache": {
        "name": "Amazon ElastiCache User Guide",
        "url": "https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/WhatIs.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    # ── Networking ─────────────────────────────────────────────────────────
    "vpc": {
        "name": "Amazon VPC User Guide",
        "url": "https://docs.aws.amazon.com/vpc/latest/userguide/what-is-amazon-vpc.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "route53": {
        "name": "Amazon Route 53 Developer Guide",
        "url": "https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/Welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "cloudfront": {
        "name": "Amazon CloudFront Developer Guide",
        "url": "https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "api_gateway": {
        "name": "Amazon API Gateway Developer Guide",
        "url": "https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    # ── Security ───────────────────────────────────────────────────────────
    "iam": {
        "name": "AWS IAM User Guide",
        "url": "https://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "kms": {
        "name": "AWS KMS Developer Guide",
        "url": "https://docs.aws.amazon.com/kms/latest/developerguide/overview.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "cognito": {
        "name": "Amazon Cognito Developer Guide",
        "url": "https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "guardduty": {
        "name": "Amazon GuardDuty User Guide",
        "url": "https://docs.aws.amazon.com/guardduty/latest/ug/what-is-guardduty.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    # ── Analytics & Data ───────────────────────────────────────────────────
    "glue": {
        "name": "AWS Glue Developer Guide",
        "url": "https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "kinesis": {
        "name": "Amazon Kinesis Data Streams Developer Guide",
        "url": "https://docs.aws.amazon.com/streams/latest/dev/introduction.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "athena": {
        "name": "Amazon Athena User Guide",
        "url": "https://docs.aws.amazon.com/athena/latest/ug/what-is.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    # ── Integration ────────────────────────────────────────────────────────
    "sqs": {
        "name": "Amazon SQS Developer Guide",
        "url": "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "sns": {
        "name": "Amazon SNS Developer Guide",
        "url": "https://docs.aws.amazon.com/sns/latest/dg/welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "eventbridge": {
        "name": "Amazon EventBridge User Guide",
        "url": "https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "step_functions": {
        "name": "AWS Step Functions Developer Guide",
        "url": "https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    # ── ML / AI ────────────────────────────────────────────────────────────
    "sagemaker": {
        "name": "Amazon SageMaker Developer Guide",
        "url": "https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "bedrock": {
        "name": "Amazon Bedrock User Guide",
        "url": "https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html",
        "source_label": "Amazon Bedrock Documentation",
        "tier": 1,
    },
    "bedrock_agentcore": {
        "name": "Amazon Bedrock AgentCore Developer Guide",
        "url": "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html",
        "source_label": "Amazon Bedrock AgentCore Documentation",
        "tier": 1,
    },
    # ── DevOps & Management ────────────────────────────────────────────────
    "cloudformation": {
        "name": "AWS CloudFormation User Guide",
        "url": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/Welcome.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "cloudwatch": {
        "name": "Amazon CloudWatch User Guide",
        "url": "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/WhatIsCloudWatch.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    "cloudtrail": {
        "name": "AWS CloudTrail User Guide",
        "url": "https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-user-guide.html",
        "source_label": "AWS Documentation",
        "tier": 1,
    },
    # ── Special Sources ────────────────────────────────────────────────────
    "prescriptive_guidance": {
        "name": "AWS Prescriptive Guidance",
        "url": "https://aws.amazon.com/prescriptive-guidance/",
        "source_label": "AWS Prescriptive Guidance",
        "tier": 2,
    },
    "solutions_library": {
        "name": "AWS Solutions Library",
        "url": "https://aws.amazon.com/solutions/",
        "source_label": "AWS Solutions Library",
        "tier": 3,
    },
    "reference_architecture": {
        "name": "AWS Reference Architecture",
        "url": "https://aws.amazon.com/architecture/",
        "source_label": "AWS Reference Architecture",
        "tier": 2,
    },
}

# Maps topic keywords typed by the user to one or more seed keys.
# Allows partial matching — the scraper checks if any key is a substring of
# the user's topic string (case-insensitive).
TOPIC_KEYWORD_MAP = {
    "serverless": ["lambda", "api_gateway", "step_functions", "eventbridge", "sqs", "sns"],
    "data pipeline": ["glue", "kinesis", "step_functions", "s3", "athena"],
    "data lake": ["s3", "glue", "athena", "redshift"],
    "machine learning": ["sagemaker", "bedrock", "s3"],
    "ml": ["sagemaker", "bedrock", "s3"],
    "ai": ["bedrock", "bedrock_agentcore", "sagemaker"],
    "generative ai": ["bedrock", "bedrock_agentcore"],
    "containers": ["ecs", "eks", "ec2"],
    "kubernetes": ["eks"],
    "database": ["rds", "dynamodb", "redshift", "elasticache"],
    "security": ["iam", "kms", "cognito", "guardduty"],
    "networking": ["vpc", "route53", "cloudfront", "api_gateway"],
    "storage": ["s3", "efs", "elasticache"],
    "analytics": ["athena", "kinesis", "glue", "redshift"],
    "monitoring": ["cloudwatch", "cloudtrail"],
    "devops": ["cloudformation", "cloudwatch", "cloudtrail"],
    "messaging": ["sqs", "sns", "eventbridge"],
    "api": ["api_gateway", "lambda"],
    "migration": ["prescriptive_guidance"],
}
