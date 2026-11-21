// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026, Eugo, Inc.
// The pages (copied into src/content/docs/ by the prepare step) and the interface texts.
import { defineCollection } from 'astro:content';
import { docsLoader, i18nLoader } from '@astrojs/starlight/loaders';
import { docsSchema, i18nSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
  i18n: defineCollection({ loader: i18nLoader(), schema: i18nSchema() }),
};
