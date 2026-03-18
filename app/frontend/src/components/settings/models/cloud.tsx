import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { authFetch } from '@/services/auth-api';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { Cloud, RefreshCw, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface CloudModelsProps {
  className?: string;
}

interface CloudModel {
  display_name: string;
  model_name: string;
  provider: string;
}

interface ModelProvider {
  name: string;
  models: Array<{
    display_name: string;
    model_name: string;
  }>;
}

interface DefaultModel {
  display_name: string;
  model_name: string;
  provider: string;
}

export function CloudModels({ className }: CloudModelsProps) {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [defaultModel, setDefaultModel] = useState<DefaultModel | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProviders = async () => {
    setLoading(true);
    setError(null);
    try {
      const [providersResponse, defaultResponse] = await Promise.all([
        authFetch(`${API_BASE_URL}/language-models/providers`),
        authFetch(`${API_BASE_URL}/language-models/default`),
      ]);

      if (!providersResponse.ok) {
        const errorData = await providersResponse.json().catch(() => ({ detail: 'Unknown error' }));
        setError(`Failed to fetch providers: ${errorData.detail}`);
        return;
      }

      const providersData = await providersResponse.json();
      setProviders(providersData.providers);

      if (defaultResponse.ok) {
        const defaultData = await defaultResponse.json();
        setDefaultModel(defaultData.model || null);
      } else {
        setDefaultModel(null);
      }
    } catch (error) {
      console.error('Failed to fetch cloud model providers:', error);
      setError('Failed to connect to backend service');
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchProviders();
  }, []);

  // Flatten all models from all providers into a single array
  const allModels: CloudModel[] = providers.flatMap(provider =>
    provider.models.map(model => ({
      ...model,
      provider: provider.name
    }))
  ).sort((a, b) => a.provider.localeCompare(b.provider));

  return (
    <div className={cn("space-y-6", className)}>

      <Card className="border-primary/20 bg-primary/5">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">Current Default Model</CardTitle>
          </div>
          <CardDescription>
            This is the unified default model resolved from the backend environment and shared by CLI, scripts, and web flows.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {defaultModel ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge className="text-xs text-primary bg-primary/10 border-primary/30 hover:bg-primary/10">
                {defaultModel.provider}
              </Badge>
              <span className="font-medium text-primary">{defaultModel.display_name}</span>
              <span className="font-mono text-xs text-muted-foreground">{defaultModel.model_name}</span>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Default model could not be resolved from the backend.</p>
          )}
        </CardContent>
      </Card>

      {error && (
        <div className="bg-red-900/20 border border-red-600/30 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <Cloud className="h-5 w-5 text-red-500 mt-0.5" />
            <div>
              <h4 className="font-medium text-red-300">Error</h4>
              <p className="text-sm text-red-500 mt-1">{error}</p>
            </div>
          </div>
        </div>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-medium text-primary
          ">Available Models</h3>
          <span className="text-xs text-muted-foreground">
            {allModels.length} models from {providers.length} providers
          </span>
        </div>

        {loading ? (
          <div className="text-center py-8">
            <RefreshCw className="h-8 w-8 mx-auto mb-2 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Loading cloud models...</p>
          </div>
        ) : allModels.length > 0 ? (
          <div className="space-y-1">
            {allModels.map((model) => (
              <div 
                key={`${model.provider}-${model.model_name}`}
                className="group flex items-center justify-between bg-muted hover-bg rounded-md px-3 py-2.5 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm truncate text-primary">{model.display_name}</span>
                    {model.model_name !== model.display_name && (
                      <span className="font-mono text-xs text-muted-foreground">
                        {model.model_name}
                      </span>
                    )}
                  </div>
                </div>
                
                <div className="flex items-center gap-2">
                  <Badge className="text-xs text-primary bg-primary/10 border-primary/30 hover:bg-primary/20 hover:border-primary/50">
                    {model.provider}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        ) : (
          !loading && (
            <div className="text-center py-8 text-muted-foreground">
              <Cloud className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No models available</p>
            </div>
          )
        )}
      </div>
    </div>
  );
} 