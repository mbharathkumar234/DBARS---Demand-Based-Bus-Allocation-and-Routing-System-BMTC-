import { Clock, Star } from "lucide-react";

type Props = {
  history: string[];
  favorites: string[];
};

export function HistoryPanel({ history, favorites }: Props) {
  return (
    <section className="dashboard-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Saved context</p>
          <h2 className="panel-title">History and favorites</h2>
        </div>
      </div>
      <div className="split-list">
        <div>
          <h3>
            <Clock size={16} /> Recent searches
          </h3>
          {history.length === 0 ? <p className="small-copy">No searches yet.</p> : history.slice(0, 6).map((item) => <span key={item}>{item}</span>)}
        </div>
        <div>
          <h3>
            <Star size={16} /> Favorite buses
          </h3>
          {favorites.length === 0 ? <p className="small-copy">No favorites yet.</p> : favorites.slice(0, 8).map((item) => <span key={item}>{item}</span>)}
        </div>
      </div>
    </section>
  );
}
