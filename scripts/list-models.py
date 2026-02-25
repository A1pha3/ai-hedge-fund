#!/usr/bin/env python3
"""
显示所有可用的大模型信息
"""

import os
from dotenv import load_dotenv
from src.llm.models import AVAILABLE_MODELS, OLLAMA_MODELS, ModelProvider

# 加载.env文件中的环境变量
load_dotenv()


def check_api_key(provider):
    """检查API key是否配置"""
    # 定义API key环境变量映射
    api_key_env_map = {
        ModelProvider.GROQ: "GROQ_API_KEY",
        ModelProvider.OPENAI: "OPENAI_API_KEY",
        ModelProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
        ModelProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
        ModelProvider.GOOGLE: "GOOGLE_API_KEY",
        ModelProvider.OPENROUTER: "OPENROUTER_API_KEY",
        ModelProvider.XAI: "XAI_API_KEY",
        ModelProvider.GIGACHAT: ["GIGACHAT_API_KEY", "GIGACHAT_CREDENTIALS", "GIGACHAT_USER", "GIGACHAT_PASSWORD"],
        ModelProvider.AZURE_OPENAI: ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT_NAME"],
        ModelProvider.ZHIPU: "ZHIPU_API_KEY",
        ModelProvider.MINIMAX: "MINIMAX_API_KEY",
        ModelProvider.OLLAMA: None  # Ollama不需要API key
    }
    
    env_vars = api_key_env_map.get(provider)
    if env_vars is None:
        return "不需要API key"
    
    if isinstance(env_vars, list):
        # 检查多个环境变量
        for env_var in env_vars:
            if os.getenv(env_var):
                return "已配置"
        return "未配置"
    else:
        # 检查单个环境变量
        if os.getenv(env_vars):
            return "已配置"
        return "未配置"


def main():
    """主函数"""
    print("可用大模型列表:")
    print("-" * 80)
    
    # 显示API模型
    print("API模型:")
    print("-" * 60)
    for model in AVAILABLE_MODELS:
        api_key_status = check_api_key(model.provider)
        print(f"模型: {model.display_name}")
        print(f"型号: {model.model_name}")
        print(f"提供商: {model.provider.value}")
        print(f"API Key状态: {api_key_status}")
        print("-" * 60)
    
    # 显示Ollama模型
    print("\nOllama本地模型:")
    print("-" * 60)
    for model in OLLAMA_MODELS:
        print(f"模型: {model.display_name}")
        print(f"型号: {model.model_name}")
        print(f"API Key状态: 不需要API key")
        print("-" * 60)
    
    # 显示使用示例
    print("\n使用示例:")
    print("  ./scripts/run-hedge-fund.sh --ticker 600158 --model gpt-4o")
    print("  ./scripts/run-hedge-fund.sh --ticker AAPL --model claude-3-opus-20240229")
    print("  ./scripts/run-hedge-fund.sh --ticker MSFT --model gemini-1.5-pro")
    print("  ./scripts/run-hedge-fund.sh --ticker TSLA --model llama3 --ollama")
    
    # 显示如何配置API key
    print("\n如何配置API key:")
    print("1. 复制 .env.example 文件为 .env")
    print("2. 在 .env 文件中添加相应的API key")
    print("   例如: OPENAI_API_KEY=your_openai_api_key")
    print("3. 保存文件后重新运行脚本")


if __name__ == "__main__":
    main()
