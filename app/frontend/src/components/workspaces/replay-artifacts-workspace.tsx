import { ReplayArtifactsSettings } from '@/components/settings/replay-artifacts';

export function ReplayArtifactsWorkspace() {
  return (
    <div className="h-full overflow-auto bg-background">
      <ReplayArtifactsSettings mode="workspace" className="mx-auto min-h-full w-full max-w-none px-6 py-6 xl:px-8" />
    </div>
  );
}