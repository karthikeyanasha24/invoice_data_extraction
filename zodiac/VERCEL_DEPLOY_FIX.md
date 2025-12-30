# 🚀 Vercel CORS Fix - Deployment Instructions

## ✅ Changes Made

1. **Updated `zodiac-api/app/server.py`**:
   - Added `https://www.bridgeedi.com` and `https://bridgeedi.com` to allowed CORS origins
   - Changed from wildcard `["*"]` to specific origins for better security
   - Added proper CORS headers configuration

2. **Updated `zodiac-api/vercel.json`**:
   - Added explicit CORS headers in Vercel configuration
   - Ensures CORS headers are sent even before FastAPI middleware processes

---

## 📋 Step-by-Step Deployment

### Step 1: Push Changes to Git

```bash
cd zodiac-api
git add app/server.py vercel.json
git commit -m "fix: Add production domain to CORS configuration"
git push origin main
```

### Step 2: Update Vercel Environment Variables

Go to your Vercel dashboard for `zodiac-back`:
1. Navigate to **Settings** → **Environment Variables**
2. Find or add `CORS_ORIGINS` variable
3. Set the value to:
   ```
   https://www.bridgeedi.com,https://bridgeedi.com,https://zodiac-front.vercel.app,http://localhost:3000
   ```
4. Click **Save**

### Step 3: Redeploy Backend

**Option A: Automatic (if you pushed to main):**
- Vercel will automatically redeploy after your git push

**Option B: Manual (via Vercel Dashboard):**
1. Go to **Deployments** tab
2. Click the **...** menu on the latest deployment
3. Click **Redeploy**
4. Check **Use existing Build Cache** ✓
5. Click **Redeploy**

### Step 4: Verify Deployment

After deployment completes (2-3 minutes):

1. **Check Deployment Logs:**
   - Look for: `🌐 CORS origins configured: ['https://www.bridgeedi.com', ...]`

2. **Test the API directly:**
   ```bash
   curl -X POST https://zodiac-back.vercel.app/api/v1/user/auth/login \
     -H "Content-Type: application/json" \
     -H "Origin: https://www.bridgeedi.com" \
     -d '{"email":"test@example.com","password":"test"}'
   ```
   
   Should return headers including:
   ```
   Access-Control-Allow-Origin: https://www.bridgeedi.com
   Access-Control-Allow-Credentials: true
   ```

3. **Test Login from Frontend:**
   - Go to https://www.bridgeedi.com
   - Try to login with your credentials
   - Should work without CORS errors

---

## 🔍 Troubleshooting

### Issue: Still getting CORS errors after deployment

**Solution:**
1. **Clear browser cache** (Ctrl + Shift + Delete) or use Incognito mode
2. **Force refresh** the frontend (Ctrl + Shift + R)
3. **Check deployment logs** on Vercel to ensure the new code is deployed

### Issue: 500 Internal Server Error

**Solution:**
1. Check Vercel Function Logs for the actual error
2. Verify `DATABASE_URL` environment variable is correct
3. Check if database is accessible from Vercel

### Issue: Environment variables not updating

**Solution:**
1. After changing environment variables, you **must redeploy**
2. Environment variables are only applied during build/deployment, not runtime

---

## 🔐 Production Environment Variables Checklist

Make sure these are set in Vercel (zodiac-back):

```env
DATABASE_URL=postgresql+asyncpg://user:password@host/database?sslmode=require
CORS_ORIGINS=https://www.bridgeedi.com,https://bridgeedi.com,https://zodiac-front.vercel.app,http://localhost:3000
JWT_SECRET=your-production-jwt-secret
OPENAI_API_KEY=your-openai-api-key
BLOB_READ_WRITE_TOKEN=your-vercel-blob-token
```

---

## 📊 Expected Result

After successful deployment:

✅ No CORS errors in browser console
✅ Login works from https://www.bridgeedi.com
✅ All API calls work normally
✅ No "Network Error" messages

---

## 🆘 Quick Fix (If Above Doesn't Work)

If you still have issues, temporarily set CORS to allow all origins:

In `zodiac-api/app/server.py`, change line 77:
```python
allow_origins=["*"],  # Temporary - allows all origins
```

Then redeploy. This will work but is less secure. Once working, switch back to specific origins.

---

## 📞 Need Help?

If issues persist:
1. Share the Vercel deployment logs
2. Share browser console errors
3. Share network tab screenshot showing the failed request

