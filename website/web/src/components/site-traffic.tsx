"use client";

import Script from "next/script";
import { useEffect, useState } from "react";

export function SiteTraffic() {
  const [published, setPublished] = useState(false);

  useEffect(() => {
    setPublished(window.location.origin === "https://fengmaker.github.io"
      && window.location.pathname.startsWith("/langrensha-site/"));
  }, []);

  return published ? (
    <Script
      type="module"
      src="https://static.cloudflareinsights.com/beacon.min.js"
      data-cf-beacon='{"token":"2794cf87e59448f68d3eea62b5002905","spa":false}'
      strategy="afterInteractive"
    />
  ) : null;
}
