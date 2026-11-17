function toTimestamp(value: string): number {
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

type ChatTimestampFields = {
  created_at: string;
  updated_at: string;
};

export function sortChatConversationsByUpdatedAt<T extends ChatTimestampFields>(
  conversations: T[]
): T[] {
  return [...conversations].sort((left, right) => {
    const updatedDelta = toTimestamp(right.updated_at) - toTimestamp(left.updated_at);
    if (updatedDelta !== 0) return updatedDelta;
    return toTimestamp(right.created_at) - toTimestamp(left.created_at);
  });
}
