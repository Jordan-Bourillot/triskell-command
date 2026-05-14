-- Lagriffe Studio — colonne brand_board_pdf_url
--
-- Ajoute le lien public Supabase Storage du PDF "brand board" (page A4
-- portrait avec palette, typos, ton, DA) joint au mail mockup envoyé
-- au client. Le PDF est généré par Puppeteer dans le workflow GitHub
-- Actions build-lagriffe-site.yml, puis uploadé dans le bucket
-- public `lagriffe-mockups`.

alter table public.lagriffe_intakes
  add column if not exists brand_board_pdf_url text;

comment on column public.lagriffe_intakes.brand_board_pdf_url is
  'URL publique du PDF brand board (page A4 jointe au mail mockup).';
