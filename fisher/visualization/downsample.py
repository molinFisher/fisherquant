import math


def lttb(data: list[tuple[float, float]], threshold: int = 500) -> list[tuple[float, float]]:
    """Largest Triangle Three Buckets downsampling algorithm.
    
    Args:
        data: List of (x, y) tuples.
        threshold: Maximum number of output points (default 500).
    
    Returns:
        Downsampled list of (x, y) tuples.
    """
    if len(data) <= threshold:
        return data

    data = list(data)
    data_length = len(data)
    bucket_size = (data_length - 2) / (threshold - 2)

    result = [data[0]]

    for i in range(1, threshold - 1):
        bucket_start = int((i - 1) * bucket_size) + 1
        bucket_end = min(int(i * bucket_size) + 1, data_length - 1)

        avg_x = 0.0
        avg_y = 0.0
        count = 0
        for j in range(bucket_start, bucket_end):
            avg_x += data[j][0]
            avg_y += data[j][1]
            count += 1
        if count == 0:
            continue
        avg_x /= count
        avg_y /= count

        prev = result[-1]
        max_area = -1.0
        max_point = data[bucket_start]

        for j in range(bucket_start, bucket_end):
            area = abs(
                (prev[0] - data[data_length - 1][0]) * (data[j][1] - prev[1])
                - (prev[0] - data[j][0]) * (data[data_length - 1][1] - prev[1])
            ) * 0.5
            if area > max_area:
                max_area = area
                max_point = data[j]

        result.append(max_point)

    result.append(data[-1])
    return result
