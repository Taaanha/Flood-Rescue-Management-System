from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class UserRoleEnum(str, PyEnum):  # type: ignore[misc]
    admin = "admin"
    coordinator = "coordinator"
    field_personnel = "field_personnel"
    volunteer_pending = "volunteer_pending"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id = Column("user_id", Integer, primary_key=True, index=True)
    person_id = Column(Integer, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column("password_hash", String(255), nullable=False)
    role_id = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)


class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(20), unique=True, nullable=True)

    volunteer_requests = relationship("VolunteerRequest", back_populates="assigned_district")


class Shelter(Base):
    __tablename__ = "shelters"

    id = Column("shelter_id", Integer, primary_key=True, index=True)
    name = Column("shelter_name", String(150), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    capacity = Column(Integer, nullable=False)
    current_occupancy = Column(Integer, nullable=True, default=0)
    status = Column(String(30), nullable=True, default="open")
    has_medical_unit = Column(Boolean, nullable=True, default=False)
    manager_id = Column(Integer, nullable=True)
    opened_at = Column(DateTime, nullable=True, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    location = relationship("Location", back_populates="shelters")


class RescueTeam(Base):
    __tablename__ = "rescue_teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    contact_number = Column(String(30), nullable=True)
    status = Column(String(30), nullable=False, default="standby")
    assets_count = Column(Integer, default=0, nullable=False)

    operations = relationship("RescueOperation", back_populates="team")


class RescueOperation(Base):
    __tablename__ = "rescue_operations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="planned")
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    team_id = Column(Integer, ForeignKey("rescue_teams.id"), nullable=True)

    team = relationship("RescueTeam", back_populates="operations")


class Person(Base):
    __tablename__ = "persons"

    id = Column("person_id", Integer, primary_key=True, index=True)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(30), nullable=True)
    email = Column(String(150), nullable=True)
    national_id = Column(String(50), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    rescue_profile = relationship("RescuePersonnel", back_populates="person", uselist=False)


class Resource(Base):
    __tablename__ = "resources"

    id = Column("resource_id", Integer, primary_key=True, index=True)
    name = Column("resource_name", String(150), nullable=False)
    unit = Column(String(50), nullable=False)
    category_id = Column(Integer, ForeignKey("resource_categories.category_id"), nullable=False)
    description = Column(Text, nullable=True)
    condition = Column(String(30), nullable=True)
    is_consumable = Column(Boolean, nullable=True, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    inventory_items = relationship("ResourceInventory", back_populates="resource")
    distributions = relationship("ResourceDistribution", back_populates="resource")
    category = relationship("ResourceCategory", back_populates="resources")


class ResourceInventory(Base):
    __tablename__ = "resource_inventory"

    id = Column("inventory_id", Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("resources.resource_id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=False)
    quantity = Column(Float, nullable=False, default=0)
    threshold = Column("minimum_threshold", Float, nullable=True, default=0)
    last_updated = Column(DateTime, nullable=True, default=datetime.utcnow)

    resource = relationship("Resource", back_populates="inventory_items")
    location = relationship("Location")


class ResourceDistribution(Base):
    __tablename__ = "resource_distributions"

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("resources.resource_id"), nullable=False)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=True)
    place = Column(String(150), nullable=True)
    quantity = Column(Float, nullable=False)
    note = Column(Text, nullable=True)
    distributed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    resource = relationship("Resource", back_populates="distributions")
    district = relationship("District")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String(30), nullable=True)
    district = Column(String(100), nullable=True)
    reported_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MonetaryDonation(Base):
    __tablename__ = "monetary_donations"

    id = Column("donation_id", Integer, primary_key=True, index=True)
    donor_id = Column(Integer, ForeignKey("donors.donor_id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), default="BDT", nullable=False)
    payment_method = Column(String(50), nullable=True)
    transaction_reference = Column(String(150), nullable=True)
    received_by = Column(Integer, nullable=True)
    status = Column(String(30), nullable=True, default="received")
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    note = Column("notes", Text, nullable=True)

    donor = relationship("Donor", back_populates="monetary_donations")


class InKindDonation(Base):
    __tablename__ = "in_kind_donations"

    id = Column("in_kind_id", Integer, primary_key=True, index=True)
    donor_id = Column(Integer, ForeignKey("donors.donor_id"), nullable=False)
    resource_id = Column(Integer, ForeignKey("resources.resource_id"), nullable=False)
    quantity = Column(Float, nullable=False)
    unit = Column(String(50), nullable=False)
    received_by = Column(Integer, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    note = Column("notes", Text, nullable=True)

    donor = relationship("Donor", back_populates="in_kind_donations")
    resource = relationship("Resource")


class VolunteerRequest(Base):
    __tablename__ = "volunteer_requests"

    id = Column(Integer, primary_key=True, index=True)
    team_name = Column(String(150), nullable=False)
    contact_number = Column(String(30), nullable=True)
    preferred_district = Column(String(100), nullable=True)
    preferred_place = Column(String(150), nullable=True)
    status = Column(String(30), nullable=False, default="pending")
    assigned_district_id = Column(Integer, ForeignKey("districts.id"), nullable=True)
    assigned_place = Column(String(150), nullable=True)
    admin_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    assigned_district = relationship("District", back_populates="volunteer_requests")


class RescuePersonnel(Base):
    __tablename__ = "rescue_personnel"

    id = Column("personnel_id", Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("persons.person_id"), nullable=False, unique=True)
    designation = Column(String(100), nullable=True)
    specialization = Column(String(100), nullable=True)
    status = Column(String(30), nullable=True, default="available")
    joined_date = Column(Date, nullable=True)
    base_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)

    person = relationship("Person", back_populates="rescue_profile")
    base_location = relationship("Location")
    team_memberships = relationship("VolunteerTeamMember", back_populates="personnel")


class Donor(Base):
    __tablename__ = "donors"

    id = Column("donor_id", Integer, primary_key=True, index=True)
    donor_name = Column(String(150), nullable=False)
    donor_type = Column(String(30), nullable=True, default="individual")
    phone = Column(String(30), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    monetary_donations = relationship("MonetaryDonation", back_populates="donor")
    in_kind_donations = relationship("InKindDonation", back_populates="donor")


class Location(Base):
    __tablename__ = "locations"

    id = Column("location_id", Integer, primary_key=True, index=True)
    area_name = Column(String(150), nullable=False)
    district = Column(String(100), nullable=False)
    division = Column(String(100), nullable=True)
    latitude = Column(Numeric(10, 7), nullable=True)
    longitude = Column(Numeric(10, 7), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    shelters = relationship("Shelter", back_populates="location")
    volunteer_teams = relationship("VolunteerTeam", back_populates="base_location")


class ResourceCategory(Base):
    __tablename__ = "resource_categories"

    id = Column("category_id", Integer, primary_key=True, index=True)
    category_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    resources = relationship("Resource", back_populates="category")


class VolunteerTeam(Base):
    __tablename__ = "volunteer_teams"

    id = Column("team_id", Integer, primary_key=True, index=True)
    team_name = Column(String(150), nullable=False, unique=True)
    leader_id = Column(Integer, ForeignKey("rescue_personnel.personnel_id"), nullable=True)
    base_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    status = Column(String(30), nullable=True, default="pending")
    reviewed_by = Column(Integer, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    base_location = relationship("Location", back_populates="volunteer_teams")
    leader = relationship("RescuePersonnel", foreign_keys=[leader_id])
    members = relationship("VolunteerTeamMember", back_populates="team")
    member_applications = relationship("VolunteerTeamApplication", back_populates="team")


class VolunteerTeamMember(Base):
    __tablename__ = "volunteer_team_members"

    team_id = Column(Integer, ForeignKey("volunteer_teams.team_id"), primary_key=True)
    personnel_id = Column(Integer, ForeignKey("rescue_personnel.personnel_id"), primary_key=True)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    team = relationship("VolunteerTeam", back_populates="members")
    personnel = relationship("RescuePersonnel", back_populates="team_memberships")


class VolunteerTeamApplication(Base):
    __tablename__ = "volunteer_team_applications"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("volunteer_teams.team_id"), nullable=False)
    full_name = Column(String(150), nullable=False)
    email = Column(String(150), nullable=True)
    phone = Column(String(30), nullable=True)
    specialization = Column(String(100), nullable=True)
    designation = Column(String(100), nullable=True)
    base_location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    is_leader = Column(Boolean, nullable=False, default=False)
    status = Column(String(30), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    team = relationship("VolunteerTeam", back_populates="member_applications")
    base_location = relationship("Location")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column("alert_id", Integer, primary_key=True, index=True)
    incident_id = Column(Integer, nullable=True)
    location_id = Column(Integer, ForeignKey("locations.location_id"), nullable=True)
    alert_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(20), nullable=True)
    status = Column(String(20), nullable=True, default="issued")
    issued_by = Column(Integer, nullable=True)
    issued_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    location = relationship("Location")

