"""An entity for a single chore."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from collections.abc import Generator
from dateutil.relativedelta import relativedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    ATTR_HIDDEN,
    CONF_NAME,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.dt import now as ha_now  # Import Home Assistant's timezone-aware `now`
from homeassistant.util.dt import as_local  # Import function to convert to local timezone

from . import const, helpers
from .const import LOGGER
from .calendar import EntitiesCalendarData

PLATFORMS: list[str] = [const.CALENDAR_PLATFORM]


class Chore(RestoreEntity):
    """Chore Sensor class."""

    __slots__ = (
        "_attr_icon",
        "_attr_name",
        "_attr_state",
        "_due_dates",
        "_date_format",
        "_days",
        "_first_month",
        "_hidden",
        "_icon_normal",
        "_icon_today",
        "_icon_tomorrow",
        "_icon_overdue",
        "_last_month",
        "_last_updated",
        "_manual",
        "_next_due_date",
        "_forecast_dates",
        "_overdue",
        "_overdue_days",
        "_frequency",
        "_start_date",
        "_offset_dates",
        "_add_dates",
        "_remove_dates",
        "show_overdue_today",
        "config_entry",
        "last_completed",
    )

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Read configuration and initialise class variables."""
        config = config_entry.options
        self.config_entry = config_entry
        self._attr_name = (
            config_entry.title
            if config_entry.title is not None
            else config.get(CONF_NAME)
        )
        self._hidden = config.get(ATTR_HIDDEN, False)
        self._manual = config.get(const.CONF_MANUAL)
        first_month = config.get(const.CONF_FIRST_MONTH, const.DEFAULT_FIRST_MONTH)
        months = [m["value"] for m in const.MONTH_OPTIONS]
        self._first_month: int = (
            months.index(first_month) + 1 if first_month in months else 1
        )
        last_month = config.get(const.CONF_LAST_MONTH, const.DEFAULT_LAST_MONTH)
        self._last_month: int = (
            months.index(last_month) + 1 if last_month in months else 12
        )
        self._icon_normal = config.get(const.CONF_ICON_NORMAL)
        self._icon_today = config.get(const.CONF_ICON_TODAY)
        self._icon_tomorrow = config.get(const.CONF_ICON_TOMORROW)
        self._icon_overdue = config.get(const.CONF_ICON_OVERDUE)
        self._date_format = config.get(
            const.CONF_DATE_FORMAT, const.DEFAULT_DATE_FORMAT
        )
        self._forecast_dates: int = config.get(const.CONF_FORECAST_DATES) or 0
        self.show_overdue_today: bool = (
            config.get(const.CONF_SHOW_OVERDUE_TODAY) or False
        )
        self._due_dates: list[date] = []
        self._next_due_date: date | None = None
        self._last_updated: datetime | None = None
        self.last_completed: datetime | None = None
        self._days: int | None = None
        self._overdue: bool = False
        self._overdue_days: int | None = None
        self._frequency: str = config.get(const.CONF_FREQUENCY)
        self._attr_state = self._days
        self._attr_icon = self._icon_normal
        self._start_date: date | None
        self._offset_dates: str = None
        self._add_dates: str = None
        self._remove_dates: str = None
        try:
            self._start_date = helpers.to_date(config.get(const.CONF_START_DATE))
        except ValueError:
            self._start_date = None

    async def async_added_to_hass(self) -> None:
        """When sensor is added to HA, restore state and add it to calendar."""
        await super().async_added_to_hass()

        # Ensure entity_id is assigned
        if not self.entity_id:
            self.entity_id = self.registry_entry.entity_id if self.registry_entry else None
            if not self.entity_id:
                LOGGER.error("Entity ID is not assigned for %s", self._attr_name)
                return

        LOGGER.debug("Entity ID assigned: %s", self.entity_id)

        self.hass.data[const.DOMAIN][const.SENSOR_PLATFORM][self.entity_id] = self

        # Restore stored state
        if (state := await self.async_get_last_state()) is not None:
            self._last_updated = None  # Unblock update - after options change
            self._attr_state = state.state
            self._days = state.attributes.get(const.ATTR_DAYS, None)
            next_due_date = (
                helpers.parse_datetime(state.attributes[const.ATTR_NEXT_DATE])
                if const.ATTR_NEXT_DATE in state.attributes
                else None
            )
            self._next_due_date = (
                None if next_due_date is None else next_due_date.date()
            )
            self.last_completed = (
                helpers.parse_datetime(state.attributes[const.ATTR_LAST_COMPLETED])
                if const.ATTR_LAST_COMPLETED in state.attributes
                else None
            )
            self._overdue = state.attributes.get(const.ATTR_OVERDUE, False)
            self._overdue_days = state.attributes.get(const.ATTR_OVERDUE_DAYS, None)
            self._offset_dates = state.attributes.get(const.ATTR_OFFSET_DATES, None)
            self._add_dates = state.attributes.get(const.ATTR_ADD_DATES, None)
            self._remove_dates = state.attributes.get(const.ATTR_REMOVE_DATES, None)

        # Create or add to calendar
        if not self.hidden:
            if const.CALENDAR_PLATFORM not in self.hass.data[const.DOMAIN]:
                self.hass.data[const.DOMAIN][const.CALENDAR_PLATFORM] = (
                    EntitiesCalendarData(self.hass)
                )
                LOGGER.debug("Creating chore calendar")
                await self.hass.config_entries.async_forward_entry_setups(
                    self.config_entry, PLATFORMS
                )

            self.hass.data[const.DOMAIN][const.CALENDAR_PLATFORM].add_entity(
                self.entity_id
            )

    async def async_will_remove_from_hass(self) -> None:
        """When sensor is removed from HA, remove it and its calendar entity."""
        await super().async_will_remove_from_hass()
        del self.hass.data[const.DOMAIN][const.SENSOR_PLATFORM][self.entity_id]
        self.hass.data[const.DOMAIN][const.CALENDAR_PLATFORM].remove_entity(
            self.entity_id
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID to use for this sensor."""
        if "unique_id" in self.config_entry.data:  # From legacy config
            return self.config_entry.data["unique_id"]
        return self.config_entry.entry_id

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def next_due_date(self) -> date | None:
        """Return next date attribute."""
        return self._next_due_date

    @property
    def overdue(self) -> bool:
        """Return overdue attribute."""
        return self._overdue

    @property
    def overdue_days(self) -> int | None:
        """Return overdue_days attribute."""
        return self._overdue_days

    @property
    def offset_dates(self) -> str:
        """Return offset_dates attribute."""
        return self._offset_dates

    @property
    def add_dates(self) -> str:
        """Return add_dates attribute."""
        return self._add_dates

    @property
    def remove_dates(self) -> str:
        """Return remove_dates attribute."""
        return self._remove_dates

    @property
    def hidden(self) -> bool:
        """Return the hidden attribute."""
        return self._hidden

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of measurement - None for numerical value."""
        return "day" if self._days == 1 else "days"

    @property
    def native_value(self) -> object:
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def last_updated(self) -> datetime | None:
        """Return when the sensor was last updated."""
        return self._last_updated

    @property
    def icon(self) -> str:
        """Return the entity icon."""
        return self._attr_icon

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {
            const.ATTR_LAST_COMPLETED: self.last_completed,
            const.ATTR_LAST_UPDATED: self.last_updated,
            const.ATTR_OVERDUE: self.overdue,
            const.ATTR_OVERDUE_DAYS: self.overdue_days,
            const.ATTR_NEXT_DATE: as_local(datetime.combine(self.next_due_date, time.min)) if self.next_due_date else None,
            const.ATTR_OFFSET_DATES: self.offset_dates,
            const.ATTR_ADD_DATES: self.add_dates,
            const.ATTR_REMOVE_DATES: self.remove_dates,
            ATTR_UNIT_OF_MEASUREMENT: self.native_unit_of_measurement,
            # Needed for translations to work
            ATTR_DEVICE_CLASS: self.DEVICE_CLASS,
            # Include frequency and period explicitly
            const.ATTR_FREQUENCY: self._frequency,
            "period": getattr(self, "_period", None),  # Ensure period is included
            # Include other initial settings
            const.ATTR_START_DATE: self._start_date,
            const.ATTR_FORECAST_DATES: self._forecast_dates,
            const.ATTR_SHOW_OVERDUE_TODAY: self.show_overdue_today,
        }

    @property
    def DEVICE_CLASS(self) -> str:  # pylint: disable=C0103
        """Return the class of the sensor."""
        return const.DEVICE_CLASS

    def __repr__(self) -> str:
        """Return main sensor parameters."""
        return (
            f"{self.__class__.__name__}(name={self._attr_name}, "
            f"entity_id={self.entity_id}, "
            f"state={self.state}, "
            f"attributes={self.extra_state_attributes})"
        )

    def _find_candidate_date(self, day1: date) -> date | None:
        """Find the next possible date starting from day1.

        Only based on calendar, not looking at include/exclude days.
        Must be implemented for each child class.
        """
        raise NotImplementedError

    async def _async_ready_for_update(self) -> bool:
        """Check if the entity is ready for the update.

        Skip the update if the sensor was updated today
        Except for the sensors with next date today and after the expiration time
        """
        current_date_time = ha_now()  # Use timezone-aware `now`
        today = current_date_time.date()
        try:
            ready_for_update = bool(self._last_updated.date() != today)  # type: ignore
        except AttributeError:
            return True
        try:
            if self._next_due_date == today and (
                isinstance(self.last_completed, datetime)
                and self.last_completed.date() == today
            ):
                return True
        except (AttributeError, TypeError):
            pass
        return ready_for_update

    def date_inside(self, dat: date) -> bool:
        """Check if the date is inside first and last date."""
        month = dat.month
        if self._first_month <= self._last_month:
            return bool(self._first_month <= month <= self._last_month)
        return bool(self._first_month <= month or month <= self._last_month)

    def move_to_range(self, day: date) -> date:
        """If the date is not in range, move to the range."""
        if not self.date_inside(day):
            year = day.year
            month = day.month
            months = [m["label"] for m in const.MONTH_OPTIONS]
            if self._first_month <= self._last_month < month:
                LOGGER.debug(
                    "(%s) %s outside the range, looking from %s next year",
                    self._attr_name,
                    day,
                    months[self._first_month - 1],
                )
                return date(year + 1, self._first_month, 1)
            LOGGER.debug(
                "(%s) %s outside the range, searching from %s",
                self._attr_name,
                day,
                months[self._first_month - 1],
            )
            return date(year, self._first_month, 1)
        return day

    def chore_schedule(self) -> Generator[date, None, None]:
        """Get dates within configured date range."""
        start_date: date = self._calculate_start_date()
        for _ in range(int(self._forecast_dates) + 1):
            try:
                next_due_date = self._find_candidate_date(start_date)
            except (TypeError, ValueError):
                break
            if next_due_date is None:
                break
            if (new_date := self.move_to_range(next_due_date)) != next_due_date:
                start_date = new_date
            else:
                should_remove = False
                if self._remove_dates is not None:
                    for remove_date in self._remove_dates.split(" "):
                        if remove_date == (next_due_date.strftime("%Y-%m-%d")):
                            should_remove = True
                            break
                if not should_remove:
                    offset = None
                    if self._offset_dates is not None:
                        offset_compare = next_due_date.strftime("%Y-%m-%d")
                        for offset_date in self._offset_dates.split(" "):
                            if offset_date.startswith(offset_compare):
                                offset = int(offset_date.split(":")[1])
                                break
                    yield (
                        next_due_date
                        if offset is None
                        else next_due_date + relativedelta(days=offset)
                    )
                start_date = next_due_date + relativedelta(
                    days=1
                )  # look from the next day
        if self._add_dates is not None:
            for add_date_str in self._add_dates.split(" "):
                yield datetime.strptime(add_date_str, "%Y-%m-%d").date()
        return

    async def complete(self, last_completed: datetime) -> None:
        """Mark the chore as completed and update the state."""
        LOGGER.debug("(%s) Completing chore with last_completed: %s", self._attr_name, last_completed)
        self.last_completed = last_completed
        await self._async_load_due_dates()
        if not self._due_dates:
            LOGGER.warning(
                "(%s) No due dates calculated after completion. Check configuration.",
                self._attr_name,
            )
        self.update_state()

    async def _async_load_due_dates(self) -> None:
        """Load due dates based on the last completed date."""
        LOGGER.debug("(%s) Loading due dates. Last completed: %s, Start date: %s", 
                     self._attr_name, self.last_completed, self._start_date)
        if self.last_completed is None:
            LOGGER.warning("(%s) Last completed is None. Using start date to calculate due dates.", self._attr_name)
            self._due_dates = [self._add_period_offset(self._start_date)]
        else:
            self._due_dates = [self._add_period_offset(self.last_completed.date())]
        LOGGER.debug("(%s) Calculated due dates: %s", self._attr_name, self._due_dates)

    async def add_date(self, chore_date: date) -> None:
        """Add date to due dates."""
        add_dates = self._add_dates.split(" ") if self._add_dates else []
        date_str = chore_date.strftime("%Y-%m-%d")
        if date_str not in add_dates:
            add_dates.append(date_str)
            add_dates.sort()
            self._add_dates = " ".join(add_dates)
        else:
            LOGGER.warning(
                "%s was already added to %s",
                chore_date,
                self.name,
            )
        self.update_state()

    async def remove_date(self, chore_date: date | None = None) -> None:
        """Remove date from chore dates."""
        if chore_date is None:
            chore_date = self.next_due_date
        if chore_date is None:
            LOGGER.warning("No date to remove from %s", self.name)
            return
        remove_dates = self._remove_dates.split(" ") if self._remove_dates else []
        date_str = chore_date.strftime("%Y-%m-%d")
        if date_str not in remove_dates:
            remove_dates.append(date_str)
            remove_dates.sort()
            self._remove_dates = " ".join(remove_dates)
        else:
            LOGGER.warning(
                "%s was already removed from %s",
                chore_date,
                self.name,
            )
        self.update_state()

    async def offset_date(self, offset: int, chore_date: date | None = None) -> None:
        """Offset date in chore dates."""
        if chore_date is None:
            chore_date = self.next_due_date
        if chore_date is None:
            LOGGER.warning("No date to offset from %s", self.name)
            return
        offset_dates = (
            [
                x
                for x in self._offset_dates.split(" ")
                if not x.startswith(chore_date.strftime("%Y-%m-%d"))
            ]
            if self._offset_dates is not None
            else []
        )
        date_str = chore_date.strftime("%Y-%m-%d")
        offset_dates.append(f"{date_str}:{offset}")
        offset_dates.sort()
        self._offset_dates = " ".join(offset_dates)
        self.update_state()

    def get_next_due_date(self, start_date: date, ignore_today=False) -> date | None:
        """Get next date from self._due_dates."""
        current_date_time = ha_now()  # Use timezone-aware `now`
        LOGGER.debug(
            "(%s) Calculating next due date: start_date=%s, ignore_today=%s, due_dates=%s",
            self._attr_name,
            start_date,
            ignore_today,
            self._due_dates,
        )
        for d in self._due_dates:  # pylint: disable=invalid-name
            if d < start_date:
                continue
            if not ignore_today and d == current_date_time.date():
                expiration = time(23, 59, 59)

                if current_date_time.time() > expiration or (
                    self.last_completed is not None
                    and self.last_completed.date() == current_date_time.date()
                    and current_date_time.time() >= self.last_completed.time()
                ):
                    continue
            LOGGER.debug("(%s) Next due date found: %s", self._attr_name, d)
            return d
        LOGGER.debug("(%s) No next due date found.", self._attr_name)
        return None

    async def async_update(self) -> None:
        """Get the latest data and updates the states."""
        if not await self._async_ready_for_update() or not self.hass.is_running:
            return

        LOGGER.debug("(%s) Calling update", self._attr_name)
        await self._async_load_due_dates()
        LOGGER.debug(
            "(%s) Dates loaded, firing a chore_helper_loaded event",
            self._attr_name,
        )
        event_data = {
            "entity_id": self.entity_id,
            "due_dates": helpers.dates_to_texts(self._due_dates),
        }
        self.hass.bus.async_fire("chore_helper_loaded", event_data)
        if not self._manual:
            self.update_state()

    def update_state(self) -> None:
        """Pick the first event from chore dates, update attributes."""
        LOGGER.debug("(%s) Looking for next chore date", self._attr_name)
        self._last_updated = ha_now()  # Use timezone-aware `now`
        today = self._last_updated.date()
        self._next_due_date = self.get_next_due_date(self._calculate_start_date())
        if self._next_due_date is not None:
            LOGGER.debug(
                "(%s) next_due_date (%s), today (%s)",
                self._attr_name,
                self._next_due_date,
                today,
            )
            self._days = (self._next_due_date - today).days
            LOGGER.debug(
                "(%s) Found next chore date: %s, that is in %d days",
                self._attr_name,
                self._next_due_date,
                self._days,
            )
            self._attr_state = self._days
            if self._days > 1:
                self._attr_icon = self._icon_normal
            elif self._days < 0:
                self._attr_icon = self._icon_overdue
            elif self._days == 0:
                self._attr_icon = self._icon_today
            elif self._days == 1:
                self._attr_icon = self._icon_tomorrow
            self._overdue = self._days < 0
            self._overdue_days = 0 if self._days > -1 else abs(self._days)
        else:
            LOGGER.warning(
                "(%s) No next_due_date found. State will be set to None.",
                self._attr_name,
            )
            self._days = None
            self._attr_state = None
            self._attr_icon = self._icon_normal
            self._overdue = False
            self._overdue_days = None

        # Add configuration attributes
        self._attr_extra_state_attributes = {
            # "frequency_type": self._frequency_type,
            "period": self._period,
            "start_date": self._start_date,
            "last_completed": self.last_completed,
            "next_due_date": self._next_due_date,
            "overdue": self._overdue,
            "overdue_days": self._overdue_days,
        }

    def calculate_day1(self, day1: date, schedule_start_date: date) -> date:
        """Calculate day1."""
        start_date = self._calculate_start_date()
        if start_date > day1:
            day1 = start_date
        if schedule_start_date > day1:
            day1 = schedule_start_date
        today = helpers.now().date()
        if (
            day1 == today
            and self.last_completed is not None
            and self.last_completed.date() == today
        ):
            day1 = day1 + relativedelta(days=1)
        return day1

    def _calculate_start_date(self) -> date:
        """Calculate start date based on the last completed date."""

        start_date = (
            self._start_date
            if self._start_date is not None
            else date(helpers.now().date().year - 1, 1, 1)
        )

        if self.last_completed is not None:
            last_completed = self.last_completed.date()

            if last_completed > start_date:
                start_date = last_completed
            elif last_completed == start_date:
                start_date += timedelta(days=1)

        return self.move_to_range(start_date)

    def _calculate_schedule_start_date(self) -> date:
        """Calculate start date for scheduling offsets."""

        after = self._frequency[:6] == "after-"
        start_date = self._start_date

        if after and self.last_completed is not None:
            earliest_date = self._add_period_offset(self.last_completed.date())

            if earliest_date > start_date:
                start_date = earliest_date

        return start_date

    def _add_period_offset(self, start_date: date) -> date:
        """Add the period offset to the start date."""
        if not hasattr(self, "_period") or self._period is None:
            raise ValueError(f"({self._attr_name}) Period is not configured.")
        next_date = start_date + timedelta(days=self._period)
        LOGGER.debug(
            "(%s) Adding period offset: start_date=%s, period=%d, next_date=%s",
            self._attr_name,
            start_date,
            self._period,
            next_date,
        )
        return next_date