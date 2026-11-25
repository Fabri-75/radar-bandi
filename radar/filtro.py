"""Decide se un avviso riguarda l'attività e perché."""
import re
from .testo import semplice


class Filtro:
    def __init__(self, imp):
        def rx(lista):
            return [(p, re.compile(r"(?<![a-z])" + re.escape(semplice(p)))) for p in (lista or [])]
        self.arg = rx(imp.get("parole_argomento"))
        self.forma = rx(imp.get("parole_forma"))
        self.escl = rx(imp.get("parole_escludi"))
        self.esito = rx(imp.get("parole_esito"))
        self.cpv = [str(c).strip() for c in (imp.get("cpv") or [])]

    @staticmethod
    def _trova(regole, s):
        return [p for p, r in regole if r.search(s)]

    def scartato(self, titolo):
        """Parola da escludere nel titolo -> motivo, altrimenti None."""
        t = self._trova(self.escl, semplice(titolo))
        return t[0] if t else None

    def argomenti(self, testo):
        return self._trova(self.arg, semplice(testo))

    def forme(self, testo):
        return self._trova(self.forma, semplice(testo))

    def e_esito(self, titolo):
        return bool(self._trova(self.esito, semplice(titolo)))

    def generico(self, titolo):
        """Titolo vago (es. 'Avviso pubblico', 'Determina n. 123'): vale la pena leggere l'allegato."""
        s = semplice(titolo)
        return bool(self.forme(s)) or bool(re.search(r"determin|decreto|avviso|bando|incaric|espert|selezion|reclutament|manifestazion|indagine|affidament|procedura|preventiv|progett|contribut|patrocini|convenzion", s))

    def cpv_utile(self, cpv):
        c = re.sub(r"\D", "", str(cpv or ""))
        return any(c.startswith(x) for x in self.cpv) if c else False
