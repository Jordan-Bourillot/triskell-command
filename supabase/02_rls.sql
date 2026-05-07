-- =====================================================================
-- Triskell Command — Row-Level Security (RLS)
-- =====================================================================
-- Politique : "tout user authentifié voit tout, peut tout éditer."
-- (Décision Jordan : il bosse avec Thomas, ils partagent tout.)
--
-- Sécurité : un utilisateur NON authentifié n'a accès à RIEN. Donc même
-- si quelqu'un trouvait l'URL Supabase + l'anon key, il ne pourrait rien
-- lire / écrire sans login.
--
-- Si un jour on veut filtrer (ex: certains templates privés), on ajoutera
-- une colonne is_private + une condition USING (is_private = false OR
-- created_by = auth.uid()).
-- =====================================================================


-- 1. Activer RLS sur toutes les tables
alter table public.users              enable row level security;
alter table public.shared_settings    enable row level security;
alter table public.prospects          enable row level security;
alter table public.email_history      enable row level security;
alter table public.prospect_drafts    enable row level security;
alter table public.templates          enable row level security;
alter table public.convoy_campaigns   enable row level security;
alter table public.convoy_drafts      enable row level security;
alter table public.send_log           enable row level security;


-- 2. Helper macro : générer les 4 policies (SELECT/INSERT/UPDATE/DELETE)
--    pour un user authentifié qui voit/édite tout.
--    Postgres n'a pas de macros, on duplique mais clean.

-- ---- users -----------------------------------------------------------
create policy "auth read users" on public.users
    for select to authenticated using (true);
create policy "auth insert users" on public.users
    for insert to authenticated with check (true);
create policy "auth update users" on public.users
    for update to authenticated using (true) with check (true);

-- ---- shared_settings -------------------------------------------------
create policy "auth read shared_settings" on public.shared_settings
    for select to authenticated using (true);
create policy "auth insert shared_settings" on public.shared_settings
    for insert to authenticated with check (true);
create policy "auth update shared_settings" on public.shared_settings
    for update to authenticated using (true) with check (true);
create policy "auth delete shared_settings" on public.shared_settings
    for delete to authenticated using (true);

-- ---- prospects -------------------------------------------------------
create policy "auth read prospects" on public.prospects
    for select to authenticated using (true);
create policy "auth insert prospects" on public.prospects
    for insert to authenticated with check (true);
create policy "auth update prospects" on public.prospects
    for update to authenticated using (true) with check (true);
create policy "auth delete prospects" on public.prospects
    for delete to authenticated using (true);

-- ---- email_history ---------------------------------------------------
create policy "auth read email_history" on public.email_history
    for select to authenticated using (true);
create policy "auth insert email_history" on public.email_history
    for insert to authenticated with check (true);

-- ---- prospect_drafts -------------------------------------------------
create policy "auth read prospect_drafts" on public.prospect_drafts
    for select to authenticated using (true);
create policy "auth insert prospect_drafts" on public.prospect_drafts
    for insert to authenticated with check (true);
create policy "auth update prospect_drafts" on public.prospect_drafts
    for update to authenticated using (true) with check (true);
create policy "auth delete prospect_drafts" on public.prospect_drafts
    for delete to authenticated using (true);

-- ---- templates -------------------------------------------------------
create policy "auth read templates" on public.templates
    for select to authenticated using (true);
create policy "auth insert templates" on public.templates
    for insert to authenticated with check (true);
create policy "auth update templates" on public.templates
    for update to authenticated using (true) with check (true);
create policy "auth delete templates" on public.templates
    for delete to authenticated using (true);

-- ---- convoy_campaigns ------------------------------------------------
create policy "auth read convoy_campaigns" on public.convoy_campaigns
    for select to authenticated using (true);
create policy "auth insert convoy_campaigns" on public.convoy_campaigns
    for insert to authenticated with check (true);
create policy "auth update convoy_campaigns" on public.convoy_campaigns
    for update to authenticated using (true) with check (true);
create policy "auth delete convoy_campaigns" on public.convoy_campaigns
    for delete to authenticated using (true);

-- ---- convoy_drafts ---------------------------------------------------
create policy "auth read convoy_drafts" on public.convoy_drafts
    for select to authenticated using (true);
create policy "auth insert convoy_drafts" on public.convoy_drafts
    for insert to authenticated with check (true);
create policy "auth update convoy_drafts" on public.convoy_drafts
    for update to authenticated using (true) with check (true);
create policy "auth delete convoy_drafts" on public.convoy_drafts
    for delete to authenticated using (true);

-- ---- send_log --------------------------------------------------------
create policy "auth read send_log" on public.send_log
    for select to authenticated using (true);
create policy "auth insert send_log" on public.send_log
    for insert to authenticated with check (true);
create policy "auth update send_log" on public.send_log
    for update to authenticated using (true) with check (true);


-- 3. Realtime : activer la publication pour les tables qui doivent
--    pousser des notifications en temps réel quand un draft est validé,
--    qu'un prospect change de statut, etc.
alter publication supabase_realtime add table public.prospects;
alter publication supabase_realtime add table public.prospect_drafts;
alter publication supabase_realtime add table public.convoy_drafts;
alter publication supabase_realtime add table public.convoy_campaigns;
alter publication supabase_realtime add table public.shared_settings;
