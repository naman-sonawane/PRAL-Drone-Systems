import type { Metadata } from "next";
import { Host_Grotesk, Instrument_Serif } from "next/font/google";
import "./globals.css";
import { AutoPilot } from "@/components/AutoPilot";
import { BlobDecorations } from "@/components/BlobDecorations";

const hostGrotesk = Host_Grotesk({
  subsets: ["latin"],
  variable: "--font-host-grotesk",
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  variable: "--font-instrument-serif",
  weight: "400",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PRAL - Autonomous Aerial Media",
  description: "Point a drone at a location. Get marketing-ready media.",
  icons: {
    icon: "/logomark.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${hostGrotesk.variable} ${instrumentSerif.variable}`}>
      <body className="font-sans antialiased">
        <BlobDecorations />
        {children}
        <AutoPilot />
      </body>
    </html>
  );
}
