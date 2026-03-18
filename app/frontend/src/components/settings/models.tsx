import { Badge } from '@/components/ui/badge';
import { getDefaultModel, type LanguageModel } from '@/data/models';
import { cn } from '@/lib/utils';
import { Cloud, Server } from 'lucide-react';
import { useEffect, useState } from 'react';
import { CloudModels } from './models/cloud';
import { OllamaSettings } from './models/ollama';

interface ModelsProps {
  className?: string;
}

interface ModelSection {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
  component: React.ComponentType;
}

export function Models({ className }: ModelsProps) {
  const [selectedSection, setSelectedSection] = useState('cloud');
  const [defaultModel, setDefaultModel] = useState<LanguageModel | null>(null);

  useEffect(() => {
    let mounted = true;

    const loadDefaultModel = async () => {
      const model = await getDefaultModel();
      if (mounted) {
        setDefaultModel(model);
      }
    };

    void loadDefaultModel();

    return () => {
      mounted = false;
    };
  }, []);

  const modelSections: ModelSection[] = [
    {
      id: 'cloud',
      label: 'Cloud',
      icon: Cloud,
      description: 'API-based models from cloud providers',
      component: CloudModels,
    },
    {
      id: 'local',
      label: 'Ollama',
      icon: Server,
      description: 'Ollama models running locally on your machine',
      component: OllamaSettings,
    },
  ];

  const renderContent = () => {
    const section = modelSections.find(s => s.id === selectedSection);
    if (!section) return null;
    
    const Component = section.component;
    return <Component />;
  };

  return (
    <div className={cn("space-y-6", className)}>
      <div>
        <h2 className="text-xl font-semibold text-primary mb-2">Models</h2>
        <p className="text-sm text-muted-foreground">
          Manage your AI models from local and cloud providers.
        </p>
      </div>

      {defaultModel && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-sm">
          <span className="text-muted-foreground">Current unified default:</span>
          <Badge className="text-xs text-primary bg-primary/10 border-primary/30 hover:bg-primary/10">
            {defaultModel.provider}
          </Badge>
          <span className="font-medium text-primary">{defaultModel.display_name}</span>
          <span className="font-mono text-xs text-muted-foreground">{defaultModel.model_name}</span>
        </div>
      )}

      {/* Model Type Navigation */}
      <div className="flex space-x-1 bg-muted p-1 rounded-lg">
        {modelSections.map((section) => {
          const Icon = section.icon;
          const isSelected = selectedSection === section.id;
          const isDisabled = false; // Enable all tabs now that cloud models is functional
          
          return (
            <button
              key={section.id}
              onClick={() => !isDisabled && setSelectedSection(section.id)}
              disabled={isDisabled}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium rounded-md transition-colors",
                isSelected 
                  ? "active-bg text-blue-500 shadow-sm" 
                  : isDisabled
                  ? "text-muted-foreground cursor-not-allowed"
                  : "text-primary hover:text-primary hover-bg"
              )}
            >
              <Icon className="h-4 w-4" />
              {section.label}
              {isDisabled && (
                <span className="text-xs bg-muted text-muted-foreground px-1.5 py-0.5 rounded">
                  Soon
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Content Area */}
      <div className="mt-6">
        {renderContent()}
      </div>
    </div>
  );
} 