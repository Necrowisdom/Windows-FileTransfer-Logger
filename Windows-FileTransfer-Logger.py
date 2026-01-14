#Engin Can Cicek


import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import logging
import shutil
import threading
from pathlib import Path

# --- Log Ayarları ---
logging.basicConfig(
    filename='dosya_hareketleri.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

class DosyaTakipUygulamasi:
    def __init__(self, pencere):
        self.pencere = pencere
        self.pencere.title("Windows Dosya Taşıma Sistemi")
        self.pencere.geometry("500x380") # İsmin rahat görünmesi için boyutu biraz artırdım

        # --- Arayüz Elemanları ---
        tk.Label(pencere, text="Kaynak Klasör:", font=('Arial', 10, 'bold')).pack(pady=(15, 0))
        self.kaynak_entry = tk.Entry(pencere, width=60)
        self.kaynak_entry.pack(pady=5)
        tk.Button(pencere, text="Klasör Seç", command=self.kaynak_sec, width=15).pack()

        tk.Label(pencere, text="Hedef Klasör:", font=('Arial', 10, 'bold')).pack(pady=(15, 0))
        self.hedef_entry = tk.Entry(pencere, width=60)
        self.hedef_entry.pack(pady=5)
        tk.Button(pencere, text="Hedef Seç", command=self.hedef_sec, width=15).pack()

        # --- İlerleme Çubuğu ---
        self.progress = ttk.Progressbar(pencere, orient="horizontal", length=400, mode="indeterminate")
        self.progress.pack(pady=25)

        # Taşıma Butonu
        self.islem_butonu = tk.Button(pencere, text="KLASÖRÜ TAŞI", bg="#28a745", fg="white", 
                                     font=('Arial', 11, 'bold'), command=self.baslat_thread,
                                     padx=20, pady=5)
        self.islem_butonu.pack()

        # --- Arayüz İçi İmza Bölümü ---
        # side="bottom" ve anchor="e" (east) ile sağ alta yaslıyoruz
        self.imza_cerceve = tk.Frame(pencere) # İmza için özel bir alan
        self.imza_cerceve.pack(side="bottom", fill="x", padx=10, pady=10)
        
        self.imza_label = tk.Label(
            self.imza_cerceve, 
            text="Developed by Engin Can Cicek", 
            font=('Segoe UI', 9, 'italic'), 
            fg="#888888" # Şık bir gri tonu
        )
        self.imza_label.pack(side="right")

    def kaynak_sec(self):
        dizin = filedialog.askdirectory()
        if dizin:
            self.kaynak_entry.delete(0, tk.END)
            self.kaynak_entry.insert(0, dizin)

    def hedef_sec(self):
        dizin = filedialog.askdirectory()
        if dizin:
            self.hedef_entry.delete(0, tk.END)
            self.hedef_entry.insert(0, dizin)

    def baslat_thread(self):
        self.islem_thread = threading.Thread(target=self.tasima_islemi)
        self.islem_thread.daemon = True # Program kapanırsa işlemi durdurması için
        self.islem_thread.start()

    def tasima_islemi(self):
        kaynak = self.kaynak_entry.get().strip()
        hedef = self.hedef_entry.get().strip()

        if not kaynak or not hedef:
            messagebox.showwarning("Uyarı", "Lütfen her iki dizini de seçin!")
            return

        self.islem_butonu.config(state="disabled")
        self.progress.start(10)

        try:
            kaynak_yolu = Path(kaynak)
            hedef_yolu = Path(hedef)

            if not kaynak_yolu.exists():
                raise FileNotFoundError("Kaynak klasör bulunamadı!")

            # Taşıma işlemi
            shutil.move(str(kaynak_yolu), str(hedef_yolu))

            logging.info(f"TASIMA_BASARILI: {kaynak} -> {hedef}")
            messagebox.showinfo("Tamamlandı", "İşlem başarıyla bitti.")
            
            self.kaynak_entry.delete(0, tk.END)
            self.hedef_entry.delete(0, tk.END)

        except Exception as e:
            logging.error(f"TASIMA_HATASI: {str(e)}")
            messagebox.showerror("Hata", f"İşlem başarısız: {e}")

        finally:
            self.progress.stop()
            self.islem_butonu.config(state="normal")

if __name__ == "__main__":
    root = tk.Tk()
    uygulama = DosyaTakipUygulamasi(root)
    root.mainloop()

# *Engin Can Cicek*
