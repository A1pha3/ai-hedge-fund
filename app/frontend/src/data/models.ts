import { api } from '@/services/api';

export interface LanguageModel {
  display_name: string;
  model_name: string;
  provider: string;
}

// Cache for models to avoid repeated API calls
let languageModels: LanguageModel[] | null = null;

/**
 * Get the list of models from the backend API
 * Uses caching to avoid repeated API calls
 */
export const getModels = async (): Promise<LanguageModel[]> => {
  if (languageModels) {
    return languageModels;
  }
  
  try {
    languageModels = await api.getLanguageModels();
    return languageModels;
  } catch (error) {
    console.error('Failed to fetch models:', error);
    throw error; // Let the calling component handle the error
  }
};

/**
 * Get the default model resolved by the backend environment
 */
export const getDefaultModel = async (): Promise<LanguageModel | null> => {
  try {
    const defaultModel = await api.getDefaultLanguageModel();
    if (defaultModel) {
      return defaultModel;
    }
    const models = await getModels();
    return models[0] || null;
  } catch (error) {
    console.error('Failed to get default model:', error);
    return null;
  }
};
