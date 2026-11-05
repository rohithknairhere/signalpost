import "./globals.css"
import type {Metadata} from 'next';
export const metadata:Metadata={title:{default:'Signalpost | Company Intelligence',template:'%s | Signalpost'},description:'Find a Norwegian company, open its profile, and see exactly where every fact came from.',openGraph:{title:'Signalpost | Company Intelligence',description:'Find a Norwegian company, open its profile, and see exactly where every fact came from.',siteName:'Signalpost',type:'website'},twitter:{card:'summary',title:'Signalpost | Company Intelligence',description:'Find a Norwegian company, open its profile, and see exactly where every fact came from.'},icons:{icon:'https://keystone.jboxai.com/project-assets/bvtpbeiegkxcvfpmod0f6yjf/id0k8z9cfjt3uxn1f9ak8kq2/5b2ede2f59b2c81b635fa939f792bf59b281aefefab6f3e2d62e115615357f83/5b2ede2f59b2c81b.svg'}};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  )
}
