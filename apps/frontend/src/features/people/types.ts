import type { LeaderboardPage } from "../../shared/api/generated/types.gen";
export type {
  Peer,
  FriendSummary,
  FriendProfile,
  FriendsPage,
  InvitePreview,
  RequestResult,
  LeaderboardPage,
  FriendRequestOutput as FriendRequest,
  InviteOutput as Invite,
  LeaderboardEntry as RankingEntry,
} from "../../shared/api/generated/types.gen";
export type Period = LeaderboardPage["period"];
export type Scope = LeaderboardPage["scope"];
export const periodLabels: Record<Period, string> = {
  week: "Эта неделя",
  month: "30 дней",
  all: "Всё время",
};
