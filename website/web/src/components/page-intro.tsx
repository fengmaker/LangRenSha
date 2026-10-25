import type { ReactNode } from "react";

export function PageIntro({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <header className="page-intro">
      <div><h1>{title}</h1>{description ? <p className="intro-copy">{description}</p> : null}</div>
      {action ? <div className="intro-action">{action}</div> : null}
    </header>
  );
}
