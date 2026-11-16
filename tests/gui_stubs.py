"""Faux modules tkinter / customtkinter pour tester le code des écrans sans écran.

Ils ne dessinent rien : ils permettent d'exécuter toute la logique des vues
(création, stock, vente, logs...) et de détecter les fautes de frappe,
les noms inconnus et les mauvaises utilisations des services.
"""

import sys
import types


class Faux:
    """Widget factice : accepte n'importe quel appel de méthode."""

    def __init__(self, *args, **kwargs):
        self._valeur = ""
        self._options = dict(kwargs)
        self._variable = kwargs.get("variable")
        valeurs = kwargs.get("values")
        if self._variable is None and valeurs:
            self._valeur = valeurs[0]

    def __getattr__(self, nom):
        def methode(*args, **kwargs):
            return Faux()
        return methode

    # --- méthodes avec comportement
    def configure(self, *args, **kwargs):
        self._options.update(kwargs)

    def cget(self, cle):
        return self._options.get(cle)

    def winfo_width(self): return 100
    def winfo_height(self): return 100
    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def winfo_screenwidth(self): return 1920
    def winfo_screenheight(self): return 1080
    def winfo_toplevel(self): return self

    def get(self):
        return self._variable.get() if self._variable is not None else self._valeur

    def set(self, valeur):
        if self._variable is not None:
            self._variable.set(valeur)
        self._valeur = valeur

    def insert(self, _index, texte):
        self._valeur = texte

    def delete(self, *args):
        self._valeur = ""

    def add(self, nom):
        return Faux()

    def tab(self, nom):
        return Faux()


class Variable:
    def __init__(self, value=None, **kwargs):
        self._v = value

    def get(self):
        return self._v

    def set(self, valeur):
        self._v = valeur


class Treeview(Faux):
    def __init__(self, master=None, columns=(), **kwargs):
        super().__init__()
        self.lignes, self._choisi, self._compteur = {}, (), 0

    def insert(self, parent, index, iid=None, values=(), tags=()):
        iid = iid if iid is not None else f"I{self._compteur}"
        self._compteur += 1
        self.lignes[iid] = (list(values), tuple(tags))
        return iid

    def delete(self, *iids):
        for iid in iids:
            self.lignes.pop(iid, None)

    def get_children(self, *args):
        return tuple(self.lignes)

    def selection(self):
        return self._choisi

    def selection_set(self, iid):
        self._choisi = (iid,)

    def item(self, iid, option=None):
        return self.lignes[iid][0] if option == "values" else {}


class Messages:
    """Enregistre les boîtes de message au lieu de les afficher."""

    def __init__(self):
        self.reinitialiser()

    def reinitialiser(self):
        self.erreurs, self.infos, self.avertissements, self.reponse_confirmation = [], [], [], True

    def showerror(self, titre, message, **kw): self.erreurs.append(message)
    def showinfo(self, titre, message, **kw): self.infos.append(message)
    def showwarning(self, titre, message, **kw): self.avertissements.append(message)
    def askyesno(self, titre, message, **kw): return self.reponse_confirmation


messages = Messages()


def installer():
    """Remplace tkinter et customtkinter par les faux modules."""
    ttk = types.ModuleType("tkinter.ttk")
    ttk.Treeview, ttk.Scrollbar, ttk.Style = Treeview, Faux, Faux
    tk = types.ModuleType("tkinter")
    tk.ttk, tk.messagebox, tk.filedialog = ttk, messages, Faux()
    tk.Tk = Faux
    ctk = types.ModuleType("customtkinter")
    for nom in ("CTk", "CTkFrame", "CTkToplevel", "CTkLabel", "CTkButton", "CTkEntry",
                "CTkOptionMenu", "CTkCheckBox", "CTkTextbox", "CTkTabview",
                "CTkScrollableFrame", "CTkFont", "CTkImage"):
        setattr(ctk, nom, Faux)
    ctk.StringVar = ctk.BooleanVar = Variable
    ctk.set_appearance_mode = ctk.set_default_color_theme = lambda *a, **k: None
    sys.modules.update({"tkinter": tk, "tkinter.ttk": ttk, "tkinter.messagebox": messages,
                        "tkinter.filedialog": tk.filedialog, "customtkinter": ctk})
