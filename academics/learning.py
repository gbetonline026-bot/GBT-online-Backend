"""Lesson ordering, unlocking and progress for an enrolment."""

from dataclasses import dataclass

from .models import Enrollment, Lesson, LessonProgress


def published_lessons(course):
    return list(
        Lesson.objects.filter(module__course=course, is_published=True)
        .select_related("module")
        .order_by("module__number", "order")
    )


@dataclass
class CourseState:
    lessons: list
    completed: set
    unlocked: set

    @property
    def total(self):
        return len(self.lessons)

    @property
    def done(self):
        return len(self.completed)

    @property
    def percent(self):
        return round(self.done * 100 / self.total) if self.total else 0

    def neighbours(self, lesson):
        ids = [item.id for item in self.lessons]
        index = ids.index(lesson.id)
        prev_lesson = self.lessons[index - 1] if index > 0 else None
        next_lesson = self.lessons[index + 1] if index + 1 < len(ids) else None
        return prev_lesson, next_lesson

    @property
    def next_lesson(self):
        for lesson in self.lessons:
            if lesson.id not in self.completed and lesson.id in self.unlocked:
                return lesson
        return self.lessons[-1] if self.lessons else None


def course_state(enrollment: Enrollment) -> CourseState:
    lessons = published_lessons(enrollment.course)
    lesson_ids = {lesson.id for lesson in lessons}
    completed = set(
        LessonProgress.objects.filter(enrollment=enrollment, lesson_id__in=lesson_ids).values_list("lesson_id", flat=True)
    )
    if not enrollment.course.sequential:
        unlocked = set(lesson_ids)
    else:
        unlocked = set()
        previous_done = True
        for lesson in lessons:
            if previous_done or lesson.id in completed:
                unlocked.add(lesson.id)
            previous_done = lesson.id in completed
    return CourseState(lessons=lessons, completed=completed, unlocked=unlocked)
