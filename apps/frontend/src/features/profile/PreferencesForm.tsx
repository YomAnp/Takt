import { useState } from "react";
import { Check } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import {
  api,
  errorText,
  type Preferences,
  type Profile,
} from "../../shared/api/client";
import { Notice } from "../../shared/ui/Notice";
export function PreferencesForm({
  profile,
  welcome,
  saved,
}: {
  profile: Profile;
  welcome?: boolean;
  saved(profile: Profile): void;
}) {
  const [name, setName] = useState(profile.display_name);
  const [end, setEnd] = useState(profile.end_time?.slice(0, 5) || "18:00");
  const mutation = useMutation({
    mutationFn: (body: Preferences) =>
      api<Profile>("/me/preferences", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: saved,
  });
  return (
    <form
      className="preferences"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate({ display_name: name.trim(), end_time: end });
      }}
    >
      <label>
        Как к вам обращаться
        <input
          name="display_name"
          autoComplete="given-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          maxLength={80}
        />
      </label>
      <label>
        Окончание рабочего дня
        <input
          name="end_time"
          type="time"
          value={end}
          onChange={(event) => setEnd(event.target.value)}
          required
        />
      </label>
      <p className="muted">
        Достаточно указать один раз. Приход вы отмечаете сами, а перерывы — по
        желанию.
      </p>
      {mutation.error && <Notice>{errorText(mutation.error)}</Notice>}
      <button
        className="primary"
        disabled={mutation.isPending || !name.trim()}
        type="submit"
      >
        {mutation.isPending
          ? "Сохраняем…"
          : welcome
            ? "Продолжить"
            : "Сохранить"}
      </button>
      {mutation.isSuccess && !welcome && (
        <p className="saved" role="status">
          <Check size={16} />
          Настройки сохранены
        </p>
      )}
    </form>
  );
}
