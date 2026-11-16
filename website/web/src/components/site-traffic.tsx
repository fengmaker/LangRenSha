"use client";

import Script from "next/script";
import { useEffect, useState } from "react";

export function SiteTraffic() {
  const [published, setPublished] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setPublished(window.location.origin === "https://fengmaker.github.io"
      && window.location.pathname.startsWith("/langrensha-site/"));
  }, []);

  return <>
    <div className="site-traffic-toggle">
      <button className="site-traffic-trigger" type="button" aria-expanded={expanded} aria-controls="site-traffic-values" onClick={() => setExpanded(!expanded)}>
        访问统计
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="m6 3 5 5-5 5" /></svg>
      </button>
      <p id="site-traffic-values" className="site-traffic" hidden={!expanded} title="浏览量按页面访问累计；访客数由不蒜子估算，仅供参考。未取得统计时显示 —。">
        <span id="busuanzi_container_site_pv">累计浏览 <b id="busuanzi_value_site_pv">—</b> 次</span>
        <span id="busuanzi_container_site_uv">累计访客 <b id="busuanzi_value_site_uv">—</b> 人次</span>
      </p>
    </div>
    {published ? <>
      <Script src="https://busuanzi.ibruce.info/busuanzi/2.3/busuanzi.pure.mini.js" strategy="afterInteractive" />
      <Script
        type="module"
        src="https://static.cloudflareinsights.com/beacon.min.js"
        data-cf-beacon='{"token":"2794cf87e59448f68d3eea62b5002905","spa":false}'
        strategy="afterInteractive"
      />
    </> : null}
  </>;
}
