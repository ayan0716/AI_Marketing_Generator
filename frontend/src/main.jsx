import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

// Shows a readable message instead of a blank white page if any component crashes.
class ErrorBoundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error("UI crash:", error, info?.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ maxWidth: 760, margin: "60px auto", padding: 24, fontFamily: "Inter, sans-serif" }}>
        <h2>Something went wrong in the page</h2>
        <pre style={{ whiteSpace: "pre-wrap", background: "#fdeceb", color: "#b42318", padding: 16, borderRadius: 12 }}>
          {String(this.state.error?.stack || this.state.error)}
        </pre>
        <button onClick={() => window.location.reload()}>Reload</button>
      </div>
    );
  }
}

createRoot(document.getElementById("root")).render(<ErrorBoundary><App /></ErrorBoundary>);