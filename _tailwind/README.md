# Regenerer le CSS Tailwind statique

Le front n'utilise plus le CDN de dev cdn.tailwindcss.com : la mise en page
est pre-compilee dans `triskell_command/web/ui/styles/tailwind.css` (commite).

Pour la regenerer apres avoir ajoute des classes Tailwind dans le HTML/JS :

```bash
cd _tailwind
npm install tailwindcss@3.4.17 @tailwindcss/forms@0.5.10 @tailwindcss/typography@0.5.16
npx tailwindcss -c ./tailwind.config.js -i ./input.css \
  -o ../triskell_command/web/ui/styles/tailwind.css --minify
```

Le `content` du config scanne index.html + login.html + scripts/*.js.
Les classes construites a la volee (`text-${couleur}`) sont dans `safelist`.
