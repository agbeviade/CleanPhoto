# Souvenir AI - Configuration Supabase

## 1. Creer le projet

1. Aller sur [supabase.com](https://supabase.com) -> New Project
2. Noter `Project URL` et `service_role key` (Settings > API)

## 2. Configurer le schema

Dans **SQL Editor**, executer le contenu de `supabase/schema.sql`.

## 3. Configurer le Storage

1. **Storage** > **Create bucket** :
   - Name: `souvenir`
   - Public: ✅ (lecture libre des images restaurees)
2. **Storage > Policies** sur le bucket `souvenir` :
   - Policy "Public read" :
     ```sql
     CREATE POLICY "Public read" ON storage.objects
       FOR SELECT TO anon
       USING (bucket_id = 'souvenir');
     ```
   - Policy "Service write" :
     ```sql
     CREATE POLICY "Service write" ON storage.objects
       FOR ALL TO service_role
       USING (bucket_id = 'souvenir')
       WITH CHECK (bucket_id = 'souvenir');
     ```

## 4. Variables d'environnement

Dans Vercel (Settings > Environment Variables) ou `.env` local :

| Variable | Valeur |
|----------|--------|
| `SUPABASE_URL` | `https://xxxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | `eyJhbGciOi...` (service_role) |
| `SUPABASE_BUCKET` | `souvenir` |
| `PIPELINE_MODE` | `lite` (sur Vercel) ou `basic` (serveur dedie) |

> ⚠️ Ne jamais exposer `SUPABASE_SERVICE_KEY` cote client (Flutter). C'est une cle admin.
> Cote app : utiliser `anon` key pour lire le storage public.

## 5. Verification

```bash
curl https://votre-app.vercel.app/api/health
```

Attendu :
```json
{
  "status": "healthy",
  "pipeline": {"mode": "lite", ...},
  "supabase": true
}
```
