import { useEffect, useRef, useState } from "react";

// Renders numeric data in monospace and briefly flashes green/red when
// `value` changes, in the direction it moved — Bloomberg-terminal style.
export default function FlashValue({
  value,
  children,
  className = "",
  style,
  as: Tag = "span",
}) {
  const prevRef = useRef(value);
  const [flash, setFlash] = useState("");

  useEffect(() => {
    const prev = prevRef.current;
    if (prev != null && value != null && value !== prev) {
      setFlash(value > prev ? "flash-up" : "flash-down");
      const t = setTimeout(() => setFlash(""), 300);
      prevRef.current = value;
      return () => clearTimeout(t);
    }
    prevRef.current = value;
  }, [value]);

  return (
    <Tag className={`mono ${className} ${flash}`.trim()} style={style}>
      {children}
    </Tag>
  );
}
