import "./globals.css"
import type {Metadata} from 'next';
export const metadata:Metadata={title:'Signalpost — Company intelligence',description:'Norwegian company intelligence, with the evidence attached.',icons:{icon:'https://keystone.jboxai.com/project-assets/bvtpbeiegkxcvfpmod0f6yjf/id0k8z9cfjt3uxn1f9ak8kq2/5b2ede2f59b2c81b635fa939f792bf59b281aefefab6f3e2d62e115615357f83/5b2ede2f59b2c81b.svg'}};

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
