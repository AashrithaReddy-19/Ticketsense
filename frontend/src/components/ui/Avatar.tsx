export function Avatar({ name, size = 34 }: { name?: string | null; size?: number }) {
  const initials = (name || "?").trim().split(/\s+/).map(part => part[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="ui-avatar" style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }} aria-hidden="true">
      {initials || "?"}
    </div>
  );
}
