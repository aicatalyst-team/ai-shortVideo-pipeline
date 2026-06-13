# PoC Plan: ai-shortVideo-pipeline

## Project Classification
- **Type:** llm-app
- **Key Technologies:** Python, FastAPI, asyncio, SQLAlchemy, Redis, MinIO, DeepSeek/Qwen LLM APIs, torch, faster-whisper
- **ODH Relevance:** Demonstrates a multi-model AI orchestration pipeline on OpenShift, coordinating multiple LLM providers with circuit breaking and failover patterns relevant to enterprise AI deployments.

## PoC Objectives
1. Validate that the FastAPI orchestrator can be containerized with UBI images and deployed on OpenShift
2. Confirm the API starts successfully with PostgreSQL and Redis backends
3. Demonstrate that the health endpoint responds and the pipeline framework initializes
4. Show CPU-only ML dependency handling (torch, faster-whisper) with UBI images

## Infrastructure Requirements
- **Resource Profile:** medium (1Gi RAM, 500m CPU)
- **GPU Required:** No (CPU-only torch variant)
- **Persistent Storage:** None (ephemeral for PoC)
- **Sidecar Containers:** PostgreSQL and Redis as separate deployments

## PoC Components
- **orchestrator** (primary) - FastAPI orchestration server

## Test Scenarios

### Scenario 1: API Health Check
- **Description:** Verify the FastAPI server starts and responds
- **Type:** http
- **Endpoint:** /docs
- **Expected:** Returns HTTP 200 with Swagger UI
- **Timeout:** 60 seconds

### Scenario 2: OpenAPI Schema
- **Description:** Verify the API schema is available
- **Type:** http
- **Endpoint:** /openapi.json
- **Expected:** Returns HTTP 200 with JSON schema
- **Timeout:** 30 seconds

## Dockerfile Considerations
- Base: `registry.access.redhat.com/ubi9/python-312`
- Replace Chinese mirror URLs with standard PyPI
- Install CPU-only torch variant
- Install ffmpeg and Chinese fonts via dnf
- Port 8000 for FastAPI/uvicorn

## Deployment Considerations
- **Deployment Model:** deployment (long-running)
- **Service:** ClusterIP on port 8000
- PostgreSQL and Redis as separate deployments
- LLM API keys optional (pipeline framework should start without them)
