import { useEffect, useState } from "react";
export function Avatar({
  name,
  url,
  large = false,
}: {
  name: string;
  url?: string | null;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const initials =
    name
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => Array.from(part)[0] || "")
      .join("") || "?";
  return (
    <span
      className={"avatar " + (large ? "avatar-large" : "")}
      aria-hidden="true"
    >
      {url?.startsWith("https://") && !failed ? (
        <img
          src={url}
          width={large ? 66 : 42}
          height={large ? 66 : 42}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        initials
      )}
    </span>
  );
}
