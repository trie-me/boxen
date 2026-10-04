import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { useSession } from "./session";
import { readPins, mergePins, MAX_PINS } from "./print-list-helpers";

const PrintListContext = createContext<{
  codes: string[];
  add: (codes: string[]) => void;
  remove: (code: string) => void;
  clear: () => void;
  notice: string;
} | null>(null);

export function PrintListProvider({ children }: { children: ReactNode }) {
  const session = useSession();
  const key = "boxen.print-list.v1:" + session.user.id;
  const [codes, setCodes] = useState<string[]>(() => {
    try {
      return readPins(localStorage.getItem(key));
    } catch {
      return [];
    }
  });
  const [notice, setNotice] = useState("");
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(codes));
    } catch {
      setNotice(
        "This browser cannot save the pin list. Keep this tab open until you print.",
      );
    }
  }, [key, codes]);
  useEffect(() => {
    function sync(event: StorageEvent) {
      if (event.key === key) setCodes(readPins(event.newValue));
    }
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, [key]);
  return (
    <PrintListContext.Provider
      value={{
        codes,
        notice,
        add: (added) => {
          if (new Set([...codes, ...added]).size > MAX_PINS) {
            setNotice(
              "A print list can hold up to 500 labels. Print or remove some labels first.",
            );
            return;
          }
          setCodes((current) => mergePins(current, added));
        },
        remove: (code) =>
          setCodes((current) => current.filter((value) => value !== code)),
        clear: () => setCodes([]),
      }}
    >
      {children}
    </PrintListContext.Provider>
  );
}

export function usePrintList() {
  const list = useContext(PrintListContext);
  if (!list) throw new Error("Print list is unavailable.");
  return list;
}

export function PrintListLink() {
  const list = usePrintList();
  if (useSession().user.role === "viewer") return null;
  return (
    <Link className="button" to="/print-list">
      Print list ({list.codes.length})
    </Link>
  );
}

export function PinLabel({
  box,
}: {
  box: { code: string; name: string; allowed_actions: string[] };
}) {
  const list = usePrintList();
  if (!box.allowed_actions.includes("label.render")) return null;
  const checked = list.codes.includes(box.code);
  return (
    <label className="print-pin">
      <input
        type="checkbox"
        checked={checked}
        disabled={!checked && list.codes.length >= MAX_PINS}
        onChange={(event) =>
          event.target.checked ? list.add([box.code]) : list.remove(box.code)
        }
        aria-label={"Pin label for " + box.name}
      />
      <span>{checked ? "Pinned for printing" : "Pin label for printing"}</span>
    </label>
  );
}
