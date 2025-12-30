# 🎨 Frontend Environment Variables - Vercel Setup

## 📋 Required Environment Variables

Go to your Vercel dashboard for the **frontend deployment** (www.bridgeedi.com):

### Navigate to: Settings → Environment Variables

Add/Update these variables:

```env
NEXT_PUBLIC_API_URL=https://zodiac-back.vercel.app
```

---

## ⚠️ Important Notes

1. **NEXT_PUBLIC_ Prefix is Required:**
   - Environment variables exposed to the browser MUST start with `NEXT_PUBLIC_`
   - Without this prefix, the variable will be `undefined` in the browser

2. **No Trailing Slash:**
   - ✅ Correct: `https://zodiac-back.vercel.app`
   - ❌ Wrong: `https://zodiac-back.vercel.app/`

3. **After Changing Environment Variables:**
   - You **MUST redeploy** the frontend
   - Environment variables are embedded at build time

---

## 🚀 Quick Deployment Steps

### 1. Set Environment Variable (if not already set)
- Go to Vercel Dashboard → Frontend Project
- Settings → Environment Variables
- Add: `NEXT_PUBLIC_API_URL` = `https://zodiac-back.vercel.app`
- Select: Production, Preview, Development (all three)
- Click **Save**

### 2. Redeploy Frontend
```bash
cd zodiac-front
git add .
git commit -m "chore: Update environment configuration"
git push origin main
```

Or manually in Vercel Dashboard:
- Deployments → Latest → ... → Redeploy

---

## ✅ Verification

After deployment, check browser console on https://www.bridgeedi.com:

1. **Open Developer Tools** (F12)
2. **Go to Console tab**
3. **Look for API request logs:**
   ```
   🚀 API Request: POST /api/v1/user/auth/login
   Base URL: https://zodiac-back.vercel.app
   Full URL: https://zodiac-back.vercel.app/api/v1/user/auth/login
   ```

4. **Should NOT see:**
   - `Base URL: http://localhost:8000` (means env var not loaded)
   - `CORS policy` errors (means backend CORS issue)
   - `Network Error` (means can't reach backend)

---

## 🔍 Common Issues

### Issue: Still using localhost in production

**Cause:** Environment variable not set or frontend not redeployed

**Solution:**
1. Double-check environment variable is set in Vercel
2. Ensure variable name is exactly: `NEXT_PUBLIC_API_URL`
3. Redeploy frontend (environment variables only apply on new builds)

### Issue: "undefined" in API URL

**Cause:** Missing `NEXT_PUBLIC_` prefix

**Solution:**
- Variable must be: `NEXT_PUBLIC_API_URL` (not just `API_URL`)

---

## 📊 Complete Environment Setup Summary

### Backend (zodiac-back.vercel.app)
```env
DATABASE_URL=postgresql+asyncpg://...
CORS_ORIGINS=https://www.bridgeedi.com,https://bridgeedi.com
JWT_SECRET=...
OPENAI_API_KEY=...
BLOB_READ_WRITE_TOKEN=...
```

### Frontend (www.bridgeedi.com)
```env
NEXT_PUBLIC_API_URL=https://zodiac-back.vercel.app
```

---

## 🎯 Quick Fix Command

If you need to quickly verify the frontend is using the correct API:

```bash
# In browser console (F12)
console.log(window.location.origin);  // Should be: https://www.bridgeedi.com
```

Then try to login and check the network tab for the API call URL.

