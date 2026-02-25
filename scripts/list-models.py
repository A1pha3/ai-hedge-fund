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
    
    # 定义默认占位符值
    default_values = [
        "your-financial-datasets-api-key",
        "your-openai-api-key",
        "your-anthropic-api-key",
        "your-groq-api-key",
        "your-google-api-key",
        "your-xai-api-key",
        "your-gigachat-api-key",
        "your-openrouter-api-key",
        "your-azure-openai-api-key",
        "your-azure-openai-endpoint",
        "your-azure-openai-deployment-name",
        "your_api_key_here"  # 智谱的默认值
    ]
    
    env_vars = api_key_env_map.get(provider)
    if env_vars is None:
        return "不需要API key"
    
    def is_valid_api_key(value):
        """检查API key是否有效"""
        # 检查值是否存在、非空、不是默认值
        if value is None:
            return False
        value_str = str(value)
        # 检查值是否为空字符串或默认值
        return len(value_str.strip()) > 0 and value_str not in default_values
    
    if isinstance(env_vars, list):
        # 检查多个环境变量
        for env_var in env_vars:
            value = os.getenv(env_var)
            if is_valid_api_key(value):
                return "已配置"
        return "未配置"
    else:
        # 检查单个环境变量
        value = os.getenv(env_vars)
        if is_valid_api_key(value):
            return "已配置"
        return "未配置"


def main():
    """主函数"""
    print("可用大模型列表:")
    print("-" * 80)
    
    # 收集已配置API key的模型
    configured_models = []
    
    # 显示API模型
    print("API模型:")
    print("-" * 60)
    for model in AVAILABLE_MODELS:
        api_key_status = check_api_key(model.provider)
        print(f"模型: {model.display_name}")
        print(f"型号: {model.model_name}")
        print(f"提供商: {model.provider.value}")
        print(f"API Key状态: {api_key_status}")
        # 添加调试信息
        if model.provider == ModelProvider.ZHIPU:
            print(f"调试信息: ZHIPU_API_KEY = {os.getenv('ZHIPU_API_KEY')}")
        elif model.provider == ModelProvider.MINIMAX:
            print(f"调试信息: MINIMAX_API_KEY = {os.getenv('MINIMAX_API_KEY')}")
        print("-" * 60)
        
        # 收集已配置的模型
        if api_key_status == "已配置":
            configured_models.append((model.model_name, model.provider))
    
    # 显示Ollama模型
    print("\nOllama本地模型:")
    print("-" * 60)
    for model in OLLAMA_MODELS:
        print(f"模型: {model.display_name}")
        print(f"型号: {model.model_name}")
        print(f"API Key状态: 不需要API key")
        print("-" * 60)
        
        # Ollama模型不需要API key，也算作可用
        configured_models.append((model.model_name, model.provider))
    
    # 显示已配置的模型列表
    print("\n已配置API key的模型（可直接使用）:")
    print("-" * 80)
    for model_name, provider in configured_models:
        print(f"- {model_name}")
    
    # 显示使用示例，使用已配置的模型
    print("\n使用示例:")
    if configured_models:
        # 使用第一个已配置的模型
        first_model = configured_models[0]
        print(f"  ./scripts/run-hedge-fund.sh --ticker 600158 --model {first_model[0]}")
        
        # 如果有多个已配置的模型，显示更多示例
        if len(configured_models) > 1:
            second_model = configured_models[1]
            print(f"  ./scripts/run-hedge-fund.sh --ticker AAPL --model {second_model[0]}")
        
        # 显示一个Ollama示例
        ollama_models = [m for m in configured_models if m[1] == ModelProvider.OLLAMA]
        if ollama_models:
            ollama_model = ollama_models[0]
            print(f"  ./scripts/run-hedge-fund.sh --ticker TSLA --model {ollama_model[0]} --ollama")
    else:
        print("  暂无已配置API key的模型，请先配置API key")
    
    # 显示如何配置API key
    print("\n如何配置API key:")
    print("1. 复制 .env.example 文件为 .env")
    print("2. 在 .env 文件中添加相应的API key")
    print("   例如: OPENAI_API_KEY=your_openai_api_key")
    print("3. 保存文件后重新运行脚本")


if __name__ == "__main__":
    main()
