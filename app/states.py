from aiogram.fsm.state import State, StatesGroup


class ScheduleSetupStates(StatesGroup):
    selecting_group = State()
    selecting_lesson_count = State()
    selecting_days = State()
    entering_time = State()
    confirming = State()


class GroupAddStates(StatesGroup):
    entering_name = State()
    selecting_teacher = State()
    selecting_lesson_count = State()
    selecting_days = State()
    choosing_time_mode = State()
    entering_time = State()
    entering_day_time = State()
    entering_fee = State()
    confirming = State()
    picking_start_date = State()


class GroupEditStates(StatesGroup):
    selecting_group = State()
    choosing_action = State()
    entering_new_name = State()
    selecting_teacher = State()
    selecting_lesson_count = State()
    selecting_days = State()
    choosing_time_mode = State()
    entering_time = State()
    entering_day_time = State()
    editing_price = State()
    confirming = State()
    confirm_delete_group = State()
    entering_chat_id = State()
    picking_start_date = State()


class FullGroupEditStates(StatesGroup):
    editing_name = State()
    editing_lesson_count = State()
    editing_days = State()
    choosing_time_mode = State()
    editing_time = State()
    entering_day_time = State()
    editing_fee = State()
    editing_chat_id = State()
    confirm_all = State()


class TeacherAddStates(StatesGroup):
    entering_full_name = State()


class TeacherSelfRegStates(StatesGroup):
    entering_full_name = State()
    sharing_phone = State()


class TeacherManageStates(StatesGroup):
    choosing_teacher = State()
    viewing_teacher = State()
    choosing_group_to_assign = State()
    confirm_delete_teacher = State()


class AdminManageStates(StatesGroup):
    viewing_admins = State()
    confirm_remove_admin = State()


class AdminSelfRegStates(StatesGroup):
    entering_full_name = State()
    sharing_phone = State()


class GroupJoinStates(StatesGroup):
    entering_full_name = State()
    sharing_phone = State()


class StudentLinkRegStates(StatesGroup):
    entering_full_name = State()
    sharing_phone = State()


class ParentRegStates(StatesGroup):
    choosing_parent_type = State()
    entering_full_name = State()
    sharing_phone = State()


class CancelLessonStates(StatesGroup):
    selecting_group = State()
    entering_reason = State()
    confirming = State()


class StudentAddStates(StatesGroup):
    choosing_method = State()
    selecting_group = State()
    entering_full_name = State()
    entering_student_phone = State()
    entering_student_tg = State()
    entering_father_phone = State()
    entering_mother_phone = State()
    entering_parent_phone = State()
    confirming = State()
    parent_batch_type = State()
    parent_batch_name = State()
    parent_batch_phone = State()
    parent_batch_child_name = State()
    parent_batch_child_group = State()
    parent_batch_add_more = State()
    parent_batch_enroll_choice = State()


class StudentManageStates(StatesGroup):
    selecting_group = State()
    selecting_student = State()
    viewing_student = State()
    editing_field = State()
    entering_new_value = State()
    selecting_new_group = State()
    confirm_keep_in_old_group = State()
    confirming_delete = State()
    select_reserve_student = State()
    select_restore_group = State()


class AttendanceStates(StatesGroup):
    selecting_group = State()
    choosing_date = State()
    marking = State()
    marking_students = State()
    selecting_session = State()
    confirming_cancel_today = State()
    editing_pending = State()
    entering_topic_date = State()
    entering_topic_title = State()
    entering_topic_details = State()
    confirm_broadcast_group = State()


class TopicStates(StatesGroup):
    selecting_group = State()
    choosing_action = State()
    selecting_date = State()
    entering_topic = State()
    entering_plan = State()
    confirming = State()
    viewing_history = State()


class PaymentStates(StatesGroup):
    selecting_group = State()
    selecting_student = State()
    selecting_cycle = State()
    confirming = State()


class ProfileEditStates(StatesGroup):
    viewing_profile = State()
    choosing_field = State()
    entering_full_name = State()
    sharing_phone = State()

class LegacyDebtStates(StatesGroup):
    entering_label = State()
    entering_dates = State()
    entering_months = State()
    entering_amount = State()
    confirming = State()


class GuestLeadStates(StatesGroup):
    choosing_course = State()
    entering_full_name = State()
    sharing_phone = State()
    confirming = State()


class CourseManageStates(StatesGroup):
    viewing = State()
    entering_name = State()
    entering_description = State()
    entering_price = State()
    entering_duration = State()
    editing_price = State()
