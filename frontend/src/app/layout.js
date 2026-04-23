import "./globals.css";

export const metadata = {
  title: "RAG Grading System",
  description: "ระบบตรวจงานด้วย AI",
};

export default function RootLayout({ children }) {
  return (
    <html lang="th">
      <body className="min-h-screen bg-gray-50 antialiased">{children}</body>
    </html>
  );
}
