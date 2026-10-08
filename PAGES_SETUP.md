# GitHub Pages — Furox Scientific Toolkit

The **gh-pages** branch contains a static copy of the production landing page, exported on 2026-10-08. Its original design and browser-only demo are preserved.

## Enable Pages without changing the MCP code on main

1. Open https://github.com/Furox-Art/scientific-toolkit/settings/pages
2. In **Build and deployment**, choose **Deploy from a branch**.
3. Choose branch **gh-pages** and **/(root)**, then **Save**.
4. Verify the fallback site: https://furox-art.github.io/scientific-toolkit/
5. After the fallback works, configure the proposed custom domain in **Pages → Custom domain**: `www.furoxscientifictoolkit.lovie.me`. GitHub may require separate ownership verification; complete that BEFORE adding DNS.
6. Only after Pages accepts the domain, add a DNS `CNAME` in LovieMe on host `www`, pointing to `furox-art.github.io`. **Do not delete or alter the existing MX and SPF records.**
7. Wait for DNS and HTTPS to validate. DNS and the GitHub Pages custom-domain acceptance were **not** completed by this commit.

Do not point `furoxscientifictoolkit.lovie.me` itself to a CNAME: that hostname already has MX and SPF and is used for email forwarding.

If GitHub rejects the custom domain because of a domain-ownership conflict, leave Vercel and ImprovMX unchanged and do not create dangling CNAME records.
