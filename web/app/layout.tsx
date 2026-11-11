import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AI跨课程知识图谱学习系统',
  description: '知识图谱学习平台',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
