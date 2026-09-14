{
  "name": "{{ project_slug }}-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "generate:icons": "oldman-web-icons --output src/generated/icons.css --source src --source ../templates --source ../apps --exclude-shared",
    "generate:i18n": "../.venv/bin/python ../scripts/build_frontend_i18n.py",
    "prebuild": "pnpm generate:icons && pnpm generate:i18n",
    "predev": "pnpm generate:icons && pnpm generate:i18n",
    "pretypecheck": "pnpm generate:icons",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    {{ frontend_dependency }},
    "@fontsource/dm-sans": "^5.2.7"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.3.0",
    "@types/node": "^22.0.0",
    "tailwindcss": "^4.3.0",
    "typescript": "^5.7.2",
    "vite": "^5.4.21"
  }
}
