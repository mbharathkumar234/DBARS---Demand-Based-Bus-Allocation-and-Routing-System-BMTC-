import { Moon, Sun } from "lucide-react";

type Props = {
  theme: "light" | "dark";
  onToggle: () => void;
};

export function ThemeToggle({ theme, onToggle }: Props) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="theme-toggle"
      aria-label="Toggle theme"
      title="Toggle theme"
    >
      {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
