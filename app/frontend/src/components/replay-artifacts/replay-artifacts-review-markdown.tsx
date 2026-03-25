import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';

interface ReplayArtifactsReviewMarkdownProps {
  markdown: string;
}

export function ReplayArtifactsReviewMarkdown({ markdown }: ReplayArtifactsReviewMarkdownProps) {
  return (
    <Accordion type="single" collapsible className="rounded-md border border-border/60 bg-muted/10 px-4">
      <AccordionItem value="review-markdown" className="border-none">
        <AccordionTrigger className="py-3 text-sm font-medium text-primary hover:no-underline">
          Selection Review Markdown
        </AccordionTrigger>
        <AccordionContent>
          <pre className="max-h-[480px] overflow-auto rounded-md border border-border/60 bg-muted/20 p-3 text-xs leading-6 whitespace-pre-wrap">
            {markdown}
          </pre>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}