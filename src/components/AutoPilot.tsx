"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { login, isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { setActiveMission, updateActiveMission, getActiveMission } from "@/lib/storage";

export function AutoPilot() {
  const pathname = usePathname();
  const router = useRouter();
  const [active, setActive] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const isAuto = localStorage.getItem("autopilot") === "true";
    setActive(isAuto);
    if (!isAuto) return;

    // Wait between 4 and 8 seconds
    const delay = Math.floor(Math.random() * 4000) + 4000;
    
    const timer = setTimeout(async () => {
      switch (pathname) {
        case "/":
          if (isAuthenticated()) {
            router.push("/target");
          } else {
            router.push("/login");
          }
          break;
        case "/login":
          {
            const emailInput = document.querySelector('input[type="email"]') as HTMLInputElement;
            const pwInput = document.querySelector('input[type="password"]') as HTMLInputElement;
            const loginBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Continue'));
            
            if (emailInput && pwInput && loginBtn) {
              const typeText = async (el: HTMLInputElement, text: string) => {
                el.value = "";
                for (let i = 0; i < text.length; i++) {
                  el.value += text[i];
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  await new Promise(r => setTimeout(r, 60 + Math.random() * 180));
                }
              };
              
              setTimeout(async () => {
                await typeText(emailInput, "namansonawane@gmail.com");
                await new Promise(r => setTimeout(r, 800 + Math.random() * 600));
                await typeText(pwInput, "123456");
                await new Promise(r => setTimeout(r, 1000 + Math.random() * 800));
                loginBtn.click();
              }, 1500);
            } else {
              login("namansonawane@gmail.com", "123456");
              router.push("/target");
            }
          }
          break;
        case "/target":
          {
            const drawBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Draw circle'));
            if (drawBtn) {
              setTimeout(() => {
                drawBtn.click();
                
                setTimeout(() => {
                  const mapContainer = document.querySelector('.leaflet-container');
                  if (mapContainer) {
                    const rect = mapContainer.getBoundingClientRect();
                    // Off-center
                    const startX = rect.left + rect.width / 2 + 60;
                    const startY = rect.top + rect.height / 2 - 40;
                    
                    // mouse down
                    mapContainer.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: startX, clientY: startY }));
                    
                    // mouse move
                    setTimeout(() => {
                      mapContainer.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: startX + 180, clientY: startY + 130 }));
                      
                      // mouse up
                      setTimeout(() => {
                        mapContainer.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: startX + 180, clientY: startY + 130 }));
                        
                        // scroll down & click acquire
                        setTimeout(() => {
                          window.scrollBy({ top: 400, behavior: "smooth" });
                          
                          setTimeout(() => {
                            const acquireBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Acquire'));
                            if (acquireBtn) acquireBtn.click();
                          }, 4000);
                        }, 2500);
                      }, 3000);
                    }, 3000);
                  }
                }, 3500);
              }, 3000);
            } else {
              // Fallback
              const aoi = {
                id: `aoi-autopilot-${pathname}`,
                center: { lat: 37.7749, lng: -122.4194 },
                radius_m: 100,
                label: "AutoPilot Target",
              };
              const mission = await api.createMission(aoi);
              setActiveMission({ ...mission, status: "processing" });
              router.push("/processing");
            }
          }
          break;
        case "/processing":
          // Handled internally by processing page
          break;
        case "/clips":
          {
            const mainArea = document.querySelector('.max-w-5xl');
            if (mainArea) {
               const btns = Array.from(mainArea.querySelectorAll('button'));
               // The clips grid buttons (exclude the Configure output button at the end)
               const clipBtns = btns.filter(b => !b.textContent?.includes('Configure output'));
               const configureBtn = btns.find(b => b.textContent?.includes('Configure output'));
               
               if (clipBtns.length > 2) {
                 setTimeout(() => {
                   window.scrollBy({ top: 250, behavior: "smooth" });
                   
                   setTimeout(() => {
                     clipBtns[0].click(); // toggle 1st
                     setTimeout(() => {
                       clipBtns[2].click(); // toggle 3rd
                       
                       setTimeout(() => {
                          if (configureBtn) configureBtn.click();
                       }, 2500);
                     }, 2000);
                   }, 1500);
                 }, 2000);
                 break;
               }
            }
            
            // Fallback
            const activeMission = getActiveMission();
            if (activeMission) {
              const clips = await api.getClips(activeMission.id);
              if (clips.length > 0) {
                updateActiveMission({
                  selected_clip_ids: [clips[0].id],
                  status: "creating",
                });
              }
            }
            router.push("/create");
          }
          break;
        case "/create":
          {
            const createArea = document.querySelector('.max-w-4xl');
            if (createArea) {
               const allBtns = Array.from(createArea.querySelectorAll('button'));
               const heroBtn = allBtns.find(b => b.textContent?.includes('Hero shot') || b.textContent?.includes('Hero'));
               const tiktokBtn = allBtns.find(b => b.textContent?.includes('TikTok') || b.textContent?.includes('YouTube'));
               const renderBtn = allBtns.find(b => b.textContent?.includes('Render previews'));
               
               if (heroBtn || tiktokBtn) {
                 setTimeout(() => {
                   window.scrollBy({ top: 150, behavior: "smooth" });
                   
                   setTimeout(() => {
                     if (heroBtn) heroBtn.click();
                     setTimeout(() => {
                       window.scrollBy({ top: 200, behavior: "smooth" });
                       
                       setTimeout(() => {
                         if (tiktokBtn) tiktokBtn.click();
                         setTimeout(() => {
                           window.scrollBy({ top: 250, behavior: "smooth" });
                           
                           setTimeout(() => {
                             if (renderBtn) renderBtn.click();
                           }, 2000);
                         }, 1500);
                       }, 1500);
                     }, 2000);
                   }, 1500);
                 }, 2000);
                 break;
               }
            }
            
            // Fallback
            updateActiveMission({ status: "preview_ready" });
            router.push("/preview");
          }
          break;
        case "/preview":
          {
             const exportBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Export'));
             if (exportBtn) {
               setTimeout(() => {
                 window.scrollBy({ top: 350, behavior: "smooth" });
                 setTimeout(() => exportBtn.click(), 3000);
               }, 2000);
             } else {
               updateActiveMission({ status: "exported" });
               router.push("/export");
             }
          }
          break;
        case "/export":
          localStorage.removeItem("autopilot");
          setActive(false);
          // Wait a bit, then redirect home
          setTimeout(() => router.push("/"), 5000);
          break;
      }
    }, pathname === "/" ? delay : 500); // Shorter delay since we have animations

    return () => clearTimeout(timer);
  }, [pathname, router]);

  if (!mounted) return null;

  return (
    <button
      onClick={() => {
        const nextActive = !active;
        if (nextActive) {
          localStorage.setItem("autopilot", "true");
          // If on home, start immediately, else reload to trigger
          if (pathname === "/") router.push("/login");
          else window.location.reload();
        } else {
          localStorage.removeItem("autopilot");
          window.location.reload();
        }
      }}
      className={`fixed bottom-6 right-6 z-[9999] px-6 py-3 rounded-full shadow-2xl transition-all duration-300 font-medium tracking-wide flex items-center gap-2 ${
        active 
          ? "bg-accent hover:bg-accent-hover text-white animate-pulse" 
          : "bg-ink hover:bg-ink-muted text-white"
      }`}
    >
      <div className={`w-2 h-2 rounded-full ${active ? "bg-white" : "bg-accent"}`} />
      {active ? "AutoPilot Active" : "Start AutoPilot"}
    </button>
  );
}
