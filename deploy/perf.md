# Front-end performance measurements

Method: Chrome via chrome-devtools-axi, a fresh browser profile per page (cold cache), network "Fast 4G", CPU 4x throttling, 12 s settle, against the local production stack (`docker-compose.prod.yml`).
Script: `measure.sh` in the session scratchpad (Performance API: LCP, JS transferred, tile timings).

## Baseline (main, 21 Oct 2026)

- {"url":"/","lcp_ms":868,"load_ms":596,"js_kb":187,"js_files":2,"total_kb":203,"requests":5,"tiles":0,"tile_p50_ms":null,"tile_p95_ms":null}
- {"url":"/map","lcp_ms":3484,"load_ms":342,"js_kb":606,"js_files":8,"total_kb":680,"requests":250,"tiles":99,"tile_p50_ms":7,"tile_p95_ms":24}
- {"url":"/dashboard","lcp_ms":3948,"load_ms":274,"js_kb":746,"js_files":20,"total_kb":849,"requests":154,"tiles":36,"tile_p50_ms":466,"tile_p95_ms":2051}
- {"url":"/assistant","lcp_ms":1200,"load_ms":779,"js_kb":573,"js_files":11,"total_kb":596,"requests":17,"tiles":0,"tile_p50_ms":null,"tile_p95_ms":null}

## Findings from the traces

- On `/map` and `/dashboard` the largest paint is the guided-tour card, which auto-starts 1.4 s after the map's layers register; LCP there measures the tour, not the map. The tour also auto-started inside the dashboard's embedded map and overlapped its layer panel (fixed: the tour now runs on the full map only).
- The entry chunk (185 KB gzip) carried the landing page's GSAP, ScrollTrigger and Lenis code into every route (fixed: landing and analytics pages are lazy; entry chunk 122 KB gzip, -34%).
- Map tiles had no Cache-Control and GFW tiles were proxied upstream on every request (fixed: SST tiles public 5 min, placeholders no-store, GFW tiles 1 h, and a shared nginx tile cache; second request for the same tile is an nginx HIT).
- The dashboard's Alerts panel presented the 2021 HAB hindcast as a live warning (fixed in the backend).

## After

Pending: the first re-measure ran while a full model retrain held the machine at load average 55 on 12 cores, which made timings meaningless (the same page varied 1.6-3.8 s between runs). To be re-measured on a quiet machine.
