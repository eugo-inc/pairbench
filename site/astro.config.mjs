// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026, Eugo, Inc.
// The documentation site. Build it with `python3 tools/docs_site.py build` from the
// repository's root; that command copies the pages of docs/ into src/content/docs/ and
// writes src/generated/site.json before Astro runs, and checks the built site after.
import { readFileSync } from 'node:fs';
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// The address of the documentation: the one setting that the links, the canonical links,
// the sitemap, robots.txt and the llms files are built for. The tool prints the same
// address after a refusal's code (DOCS_ADDRESS in src/pairbench/errors.py, kept equal by a
// test). Every page and asset lives under BASE, never at the root of the host.
const SITE = 'https://eugo.io';
const BASE = '/docs/pairbench/';

// The sidebar, the title, the version and the tags of every page's head, written by the
// prepare step from site/navigation.json, the pages themselves and the share image.
const generated = JSON.parse(
  readFileSync(new URL('./src/generated/site.json', import.meta.url), 'utf-8'),
);

export default defineConfig({
  site: SITE,
  base: BASE,
  trailingSlash: 'always',
  build: { format: 'directory' },
  integrations: [
    starlight({
      title: generated.title,
      description: generated.description,
      sidebar: generated.sidebar,
      // The tags every page names the share image with: public/share.png, drawn by
      // tools/share_image.py, with its size and its alt text.
      head: generated.head,
      // The mark beside the name in the header, in the light and the dark theme: the same files as
      // docs/readme/mark-light.svg and mark-dark.svg (a test keeps them equal).
      logo: {
        light: './src/assets/mark-light.svg',
        dark: './src/assets/mark-dark.svg',
        alt: '',
      },
      // Inter, installed from the package and served by the site itself, and the palette.
      customCss: ['@fontsource-variable/inter', './src/styles/brand.css'],
      // The footer of every page, with the line that names the maker.
      components: { Footer: './src/components/Footer.astro' },
      social: [
        { icon: 'github', label: 'Source', href: 'https://github.com/eugo-inc/pairbench' },
      ],
      // Dates come from the release, never from the history of a file, and no page says
      // who changed it or where to edit it.
      lastUpdated: false,
      credits: false,
      // The 404 page is src/pages/404.astro.
      disable404Route: true,
    }),
  ],
});
