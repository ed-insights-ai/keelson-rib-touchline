// @ts-check
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";
import starlightLlmsTxt from "starlight-llms-txt";

// Deploy defaults target this repo's GitHub Pages project URL
// (https://ed-insights-ai.github.io/keelson-rib-touchline/). For a custom domain,
// set base to "/" and add a CNAME.
export default defineConfig({
  site: "https://ed-insights-ai.github.io",
  base: "/keelson-rib-touchline",
  trailingSlash: "always",
  integrations: [
    starlight({
      title: "Keelson Rib · Touchline",
      description:
        "Touchline as a Keelson rib: on-demand collection, verification, and evidence-cited scouting reports over a consumer-owned college soccer data home.",
      favicon: "/assets/keelson-mark.svg",
      customCss: ["./src/styles/keelson-theme.css"],
      // Emits /llms.txt, /llms-full.txt, /llms-small.txt at build (llmstxt.org).
      plugins: [
        starlightLlmsTxt({
          projectName: "Keelson Rib · Touchline",
          description:
            "A Keelson rib that scouts college soccer seasons: archived-verbatim collection, canonical records, a deterministic digest, and gated, evidence-cited report generation.",
        }),
      ],
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/ed-insights-ai/keelson-rib-touchline",
        },
      ],
      sidebar: [
        { label: "Overview", link: "/" },
        { label: "Concepts", items: [{ autogenerate: { directory: "concepts" } }] },
        { label: "Guides", items: [{ autogenerate: { directory: "guides" } }] },
        { label: "Tutorials", items: [{ autogenerate: { directory: "tutorials" } }] },
        { label: "Reference", items: [{ autogenerate: { directory: "reference" } }] },
        { label: "Design", items: [{ autogenerate: { directory: "design" } }] },
      ],
    }),
  ],
});
