# Zodiac Frontend

A modern Next.js frontend for the Zodiac Invoice Management System.

## Features

- **Authentication**: Sign up and sign in functionality
- **Dashboard**: Analytics overview with recent activity
- **Invoice Management**: View and manage uploaded invoices
- **File Upload**: Drag-and-drop file upload for invoice processing
- **Responsive Design**: Mobile-friendly interface

## Tech Stack

- **Next.js 15**: React framework with App Router
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Utility-first CSS framework
- **Axios**: HTTP client for API communication
- **Lucide React**: Beautiful icons

## Getting Started

1. Install dependencies:
   ```bash
   npm install
   ```

2. Set up environment variables:
   Create a `.env.local` file with:
   ```
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

3. Start the development server:
   ```bash
   npm run dev
   ```

   Next.js defaults to **port 3000**. If that port is already in use, the local app may bind to **3001** (or the next free port). Staging/production frontends use the platform hostname (not a local port) — a 3000/3001 collision is local-only.

4. Open [http://localhost:3000](http://localhost:3000) (or the port printed by `npm run dev`) in your browser. The API is expected on `http://localhost:8000` (`NEXT_PUBLIC_API_URL`).

## Project Structure

```
src/
├── app/                 # Next.js App Router
│   ├── layout.tsx      # Root layout with AuthProvider
│   └── page.tsx        # Main page with auth routing
├── components/          # React components
│   ├── AuthForm.tsx    # Authentication form
│   └── Dashboard.tsx   # Main dashboard
├── contexts/           # React contexts
│   └── AuthContext.tsx # Authentication context
├── lib/                # Utility libraries
│   ├── api.ts          # API client
│   └── utils.ts        # Utility functions
└── types/              # TypeScript type definitions
    └── index.ts        # API and component types
```

## API Integration

The frontend integrates with the backend API running on `localhost:8000`:

- **Authentication**: `/user/auth/login`, `/user/auth/create-user`, `/user/auth/fetch_user`
- **File Management**: `/upload`, `/files`, `/files/{id}`

## Authentication Flow

1. User visits the app
2. If not authenticated, shows login/signup form
3. After successful authentication, redirects to dashboard
4. Dashboard shows analytics and invoice management
5. Users can upload files and view processing status

## File Upload

Supports drag-and-drop and click-to-upload for:
- EDI files (.edi)
- XML files (.xml)
- Text files (.txt)
- X12 files (.x12)

## Development

- Uses TypeScript for type safety
- Tailwind CSS for styling
- Responsive design for mobile and desktop
- Error handling and loading states
- Modern React patterns with hooks and context