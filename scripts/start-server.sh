#!/bin/bash

# 启动后端服务器
uv run uvicorn app.backend.main:app --reload --host 0.0.0.0 --port 8000